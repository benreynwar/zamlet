#!/usr/bin/env python3

import unittest

from liberty.parser import parse_liberty
from liberty.types import EscapedString

from asap7_liberty import normalize_library


LIBERTY = """
library (asap7_test) {
  time_unit : "1ps";
  capacitive_load_unit (1, ff);
  default_max_transition : 320;

  lu_table_template (delay) {
    variable_1 : input_net_transition;
    variable_2 : total_output_net_capacitance;
    index_1 ("5, 10");
    index_2 ("0.72, 1.44");
  }
  lu_table_template (waveform) {
    variable_1 : input_net_transition;
    variable_2 : normalized_voltage;
    index_1 ("5, 10");
    index_2 ("0.1, 0.2");
  }
  power_lut_template (power) {
    variable_1 : input_transition_time;
    index_1 ("5, 10");
  }

  normalized_driver_waveform (waveform) {
    index_1 ("5, 10");
    index_2 ("0.1, 0.2");
    values ("1, 2", "3, 4");
  }

  cell (BUF) {
    pin (A) {
      capacitance : 0.72;
      rise_capacitance_range (0.5, 1.0);
      max_transition : 320;
    }
    pin (Y) {
      max_capacitance : 46.08;
      timing () {
        cell_rise (delay) {
          values ("10, 20", "30, 40");
        }
      }
      internal_power () {
        rise_power (power) {
          values ("10, 20");
        }
      }
    }
  }
}
"""


class NormalizeAsap7LibertyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.library = normalize_library(parse_liberty(LIBERTY))

    def test_units_and_scalar_values(self) -> None:
        self.assertEqual(self.library["time_unit"], EscapedString("1ns"))
        self.assertEqual(self.library["capacitive_load_unit"], [1, "pf"])
        self.assertAlmostEqual(self.library["default_max_transition"], 0.32)

        cell = self.library.get_group("cell", "BUF")
        input_pin = cell.get_group("pin", "A")
        output_pin = cell.get_group("pin", "Y")
        self.assertAlmostEqual(input_pin["capacitance"], 0.00072)
        self.assertEqual(input_pin["rise_capacitance_range"], [0.0005, 0.001])
        self.assertAlmostEqual(input_pin["max_transition"], 0.32)
        self.assertAlmostEqual(output_pin["max_capacitance"], 0.04608)

    def test_table_axes_and_time_values(self) -> None:
        delay = self.library.get_group("lu_table_template", "delay")
        self.assertEqual(delay.get_array("index_1").tolist(), [[0.005, 0.01]])
        self.assertEqual(delay.get_array("index_2").tolist(), [[0.00072, 0.00144]])

        waveform = self.library.get_group("normalized_driver_waveform", "waveform")
        self.assertEqual(waveform.get_array("index_1").tolist(), [[0.005, 0.01]])
        self.assertEqual(waveform.get_array("index_2").tolist(), [[0.1, 0.2]])
        self.assertEqual(
            waveform.get_array("values").tolist(),
            [[0.001, 0.002], [0.003, 0.004]],
        )

        timing = (
            self.library.get_group("cell", "BUF")
            .get_group("pin", "Y")
            .get_group("timing")
            .get_group("cell_rise", "delay")
        )
        self.assertEqual(
            timing.get_array("values").tolist(),
            [[0.01, 0.02], [0.03, 0.04]],
        )

    def test_power_values_are_scaled_with_time_unit(self) -> None:
        power = (
            self.library.get_group("cell", "BUF")
            .get_group("pin", "Y")
            .get_group("internal_power")
            .get_group("rise_power", "power")
        )
        self.assertEqual(power.get_array("values").tolist(), [[0.01, 0.02]])

    def test_rejects_already_normalized_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected time_unit 1ps"):
            normalize_library(self.library)

    def test_rejects_unknown_value_table(self) -> None:
        unknown = parse_liberty(LIBERTY.replace("rise_power (power)", "mystery (power)"))
        with self.assertRaisesRegex(ValueError, "Unknown units for values"):
            normalize_library(unknown)


if __name__ == "__main__":
    unittest.main()
