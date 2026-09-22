from setuptools import find_packages, setup


version = "0.1.0"

setup(
    name="py_main_lib",
    version=version,
    packages=find_packages(),
    install_requires=[
        "fastapi==0.115.6",
        "uvicorn==0.34.0",
        "asyncpg==0.30.0",
        "hvac==2.3.0",
        "httpx==0.28.1",
        "aioboto3==15.5.0",
        "SQLAlchemy==2.0.29",
        "sqlalchemy-searchable==2.1.0",
        "SQLAlchemy-Utils==0.41.2",
        "colorlog==6.9.0",
        "python-docx==1.1.2",
        "PyPDF2==3.0.1",
    ],
)
