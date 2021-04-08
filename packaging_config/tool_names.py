import os
from pathlib import Path

# All files which start with SKOKOS are considered tools
dirs = os.listdir(Path(os.path.dirname(os.path.realpath(__file__))).parent)
tool_names = list(filter(lambda f_name: f_name.startswith("SKOPOS"),dirs))
