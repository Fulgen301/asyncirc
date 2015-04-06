from distutils.core import setup

setup(
        name="asyncirc",
        version="0.1.0",
        description="irc based on asyncio",
        author="Fox Wilson",
        author_email="fwilson@fwilson.me",
        packages=["asyncirc", "asyncirc.plugins"]
)