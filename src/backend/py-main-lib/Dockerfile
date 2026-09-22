FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y build-essential gcc g++ cmake libopenblas-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install -r requirements.txt -i https://flt:flt@nexusprojects.flt-flt.company.ru/repository/flt/simple/ --trusted-host nexusprojects.flt-flt.company.ru

RUN pip install ./py_main_lib-develop.tar.gz

ENV CC=/usr/bin/gcc
ENV CXX=/usr/bin/g++
ENV CMAKE_ARGS="-DLLAMA_BLAS=ON -DLLAMA_BLAS_VENDOR=OpenBLAS"
ENV FORCE_CMAKE=1

RUN pip install --no-cache-dir llama-cpp-python && \
    python -c "import llama_cpp; print('llama-cpp-python установлена успешно, версия:', llama_cpp.__version__)"

# FROM python:3.12-slim
#
# COPY . .
#
# RUN pip install -r requirements.txt -i https://flt:flt@nexusprojects.flt-flt.company.ru/repository/flt/simple/ --trusted-host nexusprojects.flt-flt.company.ru
#
# RUN pip install ./py_main_lib-develop.tar.gz
