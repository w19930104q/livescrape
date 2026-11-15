from setuptools import setup

setup(
    name='livescrape',
    version='0.10.0',
    url='https://github.com/ondergetekende/python-livescrape',
    description='A toolkit to build pythonic web scraper libraries',
    author='Koert van der Veer',
    author_email='koert@ondergetekende.nl',
    py_modules=["livescrape"],
    python_requires=">=3.10",
    install_requires=["lxml", "requests", "cssselect"],
    classifiers=[
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
    ],
)
