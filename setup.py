from setuptools import setup, find_packages

setup(
    name="dropin",
    version="1.0.1",
    description="Universal Linux Application Installer & Update Manager",
    author="Dropin Developers",
    author_email="support@dropin.io",
    url="https://github.com/DARKSIDE957/dropin",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "dropin": ["assets/*.svg", "assets/*.png"],
    },
    install_requires=[
        "PySide6>=6.5.0",
        "packaging>=21.0",
    ],
    entry_points={
        "console_scripts": [
            "dropin=dropin.__main__:main",
        ],
        "gui_scripts": [
            "dropin-gui=dropin.__main__:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: X11 Applications :: Qt",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: System :: Installation/Setup",
        "Topic :: Utilities",
    ],
    python_requires=">=3.9",
)
