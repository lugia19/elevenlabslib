import setuptools

setuptools.setup(
    name="elevenlabspy",
    version="0.1",
    description="Python implementation of ElevenLabs' API",
    author="lugia19",
    author_email="lugia19@lugia19.com",
    url="TBA",
    packages=setuptools.find_packages(),
    install_requires=[
        "requests",
        "logging",
        "json",
        "io",
        "zipfile",
        "typing"
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "Development Status :: 1 - Planning"
    ]
)