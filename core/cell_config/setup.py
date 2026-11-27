from setuptools import find_packages, setup

setup(
    name="cell_config",
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/cell_config"]),
        ("share/cell_config", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="user",
    maintainer_email="user@todo.todo",
    description="Persistent robot cell configuration HTTP backend",
    license="MIT",
    entry_points={
        "console_scripts": [
            "cell_config = cell_config.node:main",
            "cell_deploy = cell_config.deploy:main",
        ]
    },
)
