import os
import subprocess
from typing import List

this_dir = os.path.abspath(os.path.dirname(__file__))


def generate(module_name: str, working_dir: str, args: List[str]) -> List[str]:
    """Call the fmpvu RTL generator using 'mill'.
    
    # FIXME: This is hacky. Find a better way.
    """
    working_dir = os.path.abspath(working_dir)
    mill_dir = os.path.abspath(os.path.join(this_dir, '..', '..', '..', '..'))
    mill = os.path.join(mill_dir, 'mill')
    # Fix argument order: Main.scala expects [outputDir, moduleName, ...]
    result = subprocess.run([mill, 'fmpvu.run', '--', working_dir, module_name] + args,
                   check=False, cwd=mill_dir)
    assert result.returncode == 0
    filenames = [os.path.join(working_dir, fn)
                 for fn in os.listdir(working_dir) if fn[-3:] == '.sv']
    return filenames
