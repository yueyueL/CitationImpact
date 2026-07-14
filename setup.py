import re
from pathlib import Path

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

# Single source of truth for the version: citationimpact/__init__.py
_init = Path("citationimpact/__init__.py").read_text(encoding="utf-8")
version = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", _init).group(1)

setup(
    name="citationimpact",
    version=version,
    author="CitationImpact Contributors",
    description="Academic Impact Report Tool for Grant Applications and Performance Reviews",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/CitationImpact",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "citation-impact=citationimpact.cli:main",
            "citationimpact-ui=citationimpact.ui.app:main",
        ],
    },
    package_data={
        "citationimpact": [
            "data/**/*",
        ],
    },
    include_package_data=True,
)
