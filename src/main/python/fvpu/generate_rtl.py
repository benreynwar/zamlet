import os
import subprocess

this_dir = os.path.abspath(os.path.dirname(__file__))


def generate(module_name, working_dir, args):
    '''
    Call the fvpu RTL generator using 'mill'.
    #FIXME: This is hacky.  Find a better way.
    '''
    working_dir = os.path.abspath(working_dir)
    mill_dir = os.path.abspath(os.path.join(this_dir, '..', '..' , '..', '..'))
    mill = os.path.join(mill_dir, 'mill')
    # Fix argument order: Main.scala expects [outputDir, moduleName, ...]
    result = subprocess.run([mill, 'fvpu.run', '--', working_dir, module_name] + args,
                   check=False, cwd=mill_dir)
    assert result.returncode == 0
    filenames = [os.path.join(working_dir, fn)
                 for fn in os.listdir(working_dir) if fn[-3:] == '.sv']
    return filenames
