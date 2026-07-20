import json
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import rich.console
import rich.table

from librelane.common import _get_process_limit, aggregate_metrics, mkdirp
from librelane.logging import console, info, options
from librelane.state import DesignFormat
from librelane.steps import Step, TclStep
from librelane.steps.openroad import MultiCornerSTA, OpenROADStep


@Step.factory.register()
class STAMidPNRMultiCorner(MultiCornerSTA):
    id = "Zamlet.STAMidPNRMultiCorner"
    name = "STA (Mid-PnR, Multi-Corner)"
    long_name = "Static Timing Analysis (Mid-PnR, Multi-Corner)"

    inputs = [DesignFormat.ODB]
    outputs = []

    def get_command(self):
        return OpenROADStep.get_command(self)

    def run_corner(self, state_in, current_env, corner, corner_dir):
        _, file_list = self._get_corner_files(
            corner,
            prioritize_nl=self.config["STA_MACRO_PRIORITIZE_NL"],
        )
        current_env["_LIB_CORNER_0"] = TclStep.value_to_tcl(
            [corner] + list(file_list.libs)
        )
        info(f"Starting STA for the {corner} timing corner...")
        current_env["_CURRENT_CORNER_NAME"] = corner
        log_path = os.path.join(corner_dir, "sta.log")
        metrics_path = os.path.join(corner_dir, "or_metrics_out.json")
        command = [
            self.get_openroad_path(),
            ("-gui" if os.getenv("_OPENROAD_GUI", "0") == "1" else "-exit"),
            "-no_splash",
            "-metrics",
            metrics_path,
            self.get_script_path(),
        ]

        subprocess_result = self.run_subprocess(
            command,
            log_to=log_path,
            env=current_env,
            silent=True,
            report_dir=corner_dir,
        )

        generated_metrics = subprocess_result["generated_metrics"]
        if os.path.exists(metrics_path):
            generated_metrics.update(
                json.loads(open(metrics_path).read(), parse_float=Decimal)
            )

        info(f"Finished STA for the {corner} timing corner.")
        return generated_metrics

    def run(self, state_in, **kwargs):
        kwargs, env = self.extract_env(kwargs)
        env = self.prepare_env(env, state_in)

        futures = {}
        tpe = ThreadPoolExecutor(
            max_workers=self.config["STA_THREADS"] or _get_process_limit()
        )
        for corner in self.config["STA_CORNERS"]:
            _, file_list = self._get_corner_files(
                corner,
                prioritize_nl=self.config["STA_MACRO_PRIORITIZE_NL"],
            )
            current_env = env.copy()
            file_list.set_env(current_env)

            corner_dir = os.path.join(self.step_dir, corner)
            mkdirp(corner_dir)
            futures[corner] = tpe.submit(
                self.run_corner,
                state_in,
                current_env,
                corner,
                corner_dir,
            )

        metrics_updates = {}
        for updates_future in futures.values():
            metrics_updates.update(updates_future.result())

        metric_updates_with_aggregates = aggregate_metrics(metrics_updates)

        def format_count(count):
            if count is None:
                return "[gray]?"
            count = int(count)
            if count == 0:
                return f"[green]{count}"
            return f"[red]{count}"

        def format_slack(slack):
            if slack is None:
                return "[gray]?"
            if slack == float("inf"):
                return "[gray]N/A"
            slack = round(float(slack), 4)
            formatted_slack = f"{slack:.4f}"
            if slack < 0:
                return f"[red]{formatted_slack}"
            return f"[green]{formatted_slack}"

        table = rich.table.Table()
        table.add_column("Corner/Group", width=20)
        table.add_column("Hold Worst Slack")
        table.add_column("Reg to Reg Paths")
        table.add_column("Hold TNS")
        table.add_column("Hold Vio Count")
        table.add_column("of which reg to reg")
        table.add_column("Setup Worst Slack")
        table.add_column("Reg to Reg Paths")
        table.add_column("Setup TNS")
        table.add_column("Setup Vio Count")
        table.add_column("of which reg to reg")
        table.add_column("Max Cap Violations")
        table.add_column("Max Slew Violations")
        for corner in ["Overall"] + self.config["STA_CORNERS"]:
            modifier = ""
            if corner != "Overall":
                modifier = f"__corner:{corner}"
            row = [corner]
            for metric in [
                "timing__hold__ws",
                "timing__hold_r2r__ws",
                "timing__hold__tns",
                "timing__hold_vio__count",
                "timing__hold_r2r_vio__count",
                "timing__setup__ws",
                "timing__setup_r2r__ws",
                "timing__setup__tns",
                "timing__setup_vio__count",
                "timing__setup_r2r_vio__count",
                "design__max_cap_violation__count",
                "design__max_slew_violation__count",
            ]:
                formatter = format_count if metric.endswith("count") else format_slack
                row.append(
                    formatter(metric_updates_with_aggregates.get(f"{metric}{modifier}"))
                )
            table.add_row(*row)

        if not options.get_condensed_mode():
            console.print(table)
        file_console = rich.console.Console(
            file=open(os.path.join(self.step_dir, "summary.rpt"), "w", encoding="utf8"),
            width=160,
        )
        file_console.print(table)

        return {}, metric_updates_with_aggregates
