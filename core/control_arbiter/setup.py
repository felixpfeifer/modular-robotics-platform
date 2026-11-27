from glob import glob

from setuptools import find_packages, setup


package_name = "control_arbiter"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="user",
    maintainer_email="user@todo.todo",
    description="ROS 2 command source arbiter for the SO-101 follower",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "arbiter = control_arbiter.arbiter:main",
            "teleop_source = control_arbiter.teleop_source:main",
            "policy_source = control_arbiter.policy_source:main",
        ],
    },
)
