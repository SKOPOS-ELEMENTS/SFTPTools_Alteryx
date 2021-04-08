import tempfile
from typing import List

from invoke import task
import os, sys
import shutil
import subprocess
import packaging_config.tool_names as tn

# ---------------------------------------GLOBAL VARIABLES------------------------------------------#
# Path to user plugins/tools
alteryx_engine = f"C:\\Program Files\\Alteryx\\bin\\AlteryxEngineCmd.exe"
alteryx_miniconda = f"C:\\Program Files\\Alteryx\\bin\\Miniconda3\\python.exe"
tool_base_dir = os.path.dirname(os.path.realpath(__file__))
project_name = "SKOPOSSFTP_v1" # os.path.basename(tool_base_dir)

try:
    user_tools_path = os.path.join(f"{os.environ['APPDATA']}", "Alteryx", "Tools")
except KeyError:
    print(
        "Not able to find APPDATA environment variable. This is expected on Linux/Gitlab CI"
    )

try:
    user_tools_path = os.path.join(f"{os.environ['APPDATA']}", "Alteryx", "Tools")
except KeyError:
    print(
        "Not able to find APPDATA environment variable. This is expected on Linux/Gitlab CI"
    )
snakeplane_path = os.path.join("..", "snakeplane")
extras = []


def _make_list_of_ignored_files(files: List[str], full_names: List[str], suffix_list: List[str], pref_list: List[str]):
    ignored_files: List[str] = full_names

    for file in files:
        for suffix in suffix_list:
            if file.endswith(suffix):
                ignored_files.append(file)
        for pref in pref_list:
            if file.startswith(pref):
                ignored_files.append(file)
    return ignored_files


def _installer_exists():
    return os.path.exists(f"{tool_base_dir}/packaging_config/Installer_Config.xml")


def _copy_installer_to_temp(temp_dir: str):
    shutil.copytree(f"{tool_base_dir}/packaging_config", f"{temp_dir}",
                    ignore=lambda dir, file: ["Installer_Config.xml", "tool_names.py"])
    shutil.copy(f"{tool_base_dir}/packaging_config/Installer_Config.xml", f"{temp_dir}/Config.xml")


# files and directories to ignore for export
def _dirs_and_files_to_exclude_from_packaging(dir, files):
    full_file_names = ["Scripts", "Lib", "Include", ".idea", "env", ".gitignore", ".gitmodules","tests"]
    suffixes = [".pyc", ".log", ".bat", ".sh"]
    prefixes = [".git"]
    return _make_list_of_ignored_files(files=files, full_names=full_file_names, suffix_list=suffixes,
                                       pref_list=prefixes)


def _copy_tools_to_temp(tool_names: List[str], temp_dir: str):
    for tool in tool_names:
        print(f"Copy tool {tool} to installer...")
        if not os.path.exists(f"{tool_base_dir}/{tool}"):
            print(f"Tool {tool} does not Exist! It will be skipped")
            continue

        shutil.copytree(f"{tool_base_dir}/{tool}", f"{temp_dir}/{tool}",
                        ignore=_dirs_and_files_to_exclude_from_packaging)
        shutil.copy(f"{tool_base_dir}/requirements.txt", f"{temp_dir}/{tool}/requirements.txt")

def _create_intaller(temp_dir: str, installer_name: str):
    shutil.make_archive(f"{tool_base_dir}/alteryx_installer/{installer_name}", "zip", f"{temp_dir}")
    if os.path.exists(f"{tool_base_dir}/alteryx_installer/{installer_name}.yxi"):
        os.remove(f"{tool_base_dir}/alteryx_installer/{installer_name}.yxi")
    os.rename(f"{tool_base_dir}/alteryx_installer/{installer_name}.zip",
              f"{tool_base_dir}/alteryx_installer/{installer_name}.yxi")
    return f"{tool_base_dir}/alteryx_installer/{installer_name}.yxi"


# ------------------------------------------------------------------------------------------------- #

@task(
    help={
        "name": "Specified name for the yxi",
    }
)
def package(c, name=project_name):
    """
    Bundles a folder into a yxi
    """
    tool_names = tn.tool_names

    if not _installer_exists():
        print(f"Installer Config not found. "
              f"Expected configuration at: {tool_base_dir}/packaging_config/Installer_Config.xml")
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = os.path.join(temp_dir, "proj")
        _copy_installer_to_temp(temp_dir=temp_dir)
        _copy_tools_to_temp(tool_names=tool_names, temp_dir=temp_dir)
        installer_path = _create_intaller(temp_dir=temp_dir, installer_name=project_name)

    print(f"Installer created: {installer_path} \nincluded tools: {tool_names}")


@task
def debug(c, name):
    """
    Run's the tool's debug workflow in the console
    """

    workflow = f"./debug_workflows/{name}.yxmd"

    if not os.path.exists(workflow):
        print(f"{name}.yxmd does not exist.\nYou need to setup a debug workflow")
        return
    subprocess.call(
        [
            "C:\\WINDOWS\\system32\\WindowsPowerShell\\v1.0\\powershell.exe",
            f"& '{alteryx_engine}' {workflow}",
        ]
    )


@task
def freeze(c):
    """
    Saves the workspaces current dependencies
    """

    os.system(f"{tool_base_dir}/env/Scripts/pip.exe freeze > {tool_base_dir}/requirements.txt")
    print(f"requirements.txt updated.")


@task(
    help={
        "tool_name": "Name of the tool folder which should be linked",
    }
)
def link(c, tool_name, force=False):
    """
    Creates symbolic link to alteryx tool folder to be able to use the tool in alteryx
    """

    tool_dir = os.path.join(tool_base_dir, tool_name)

    if not os.path.exists(tool_dir):
        print(f"No tool with name '{tool_name}' was found in directory '{tool_base_dir}'. Please check the spelling.")
        return
    elif not os.path.exists(f"{tool_dir}/{tool_name}Config.xml"):
        print(f"No {tool_name}Config.xml found. Porject would not work in Alteryx")
        return

    target_dir = os.path.join(user_tools_path, tool_name)
    if os.path.exists(target_dir):

        if force:
            print("Remove old tool with same name ...", os.path.exists(target_dir), os.path.islink(target_dir))
            if os.path.islink(target_dir):
                os.remove(target_dir)
            else:
                os.rmdir(target_dir)

            assert (not os.path.exists(target_dir))

            print("Removed ", not os.path.exists(target_dir))
        else:
            print(
                f"Tool '{tool_name}' already exists in directory '{user_tools_path}'. add parameter -f to replace file.")
            return

    # link env
    env_dir = os.path.join(tool_base_dir, "env")
    if not os.path.exists(env_dir):
        print("Warning: No 'env' directory available could not link environment")
    else:
        for dir in ["Scripts", "Include", "Lib"]:
            dir_path = os.path.join(tool_dir, dir)

            if os.path.exists(dir_path) or os.path.islink(dir_path):
                print(f"{dir} already exists.")
            else:
                os.symlink(os.path.join(env_dir, dir), os.path.join(tool_dir, dir))

    # link env
    os.symlink(tool_dir, target_dir)

    print("Link to alteryx created.")
