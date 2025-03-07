@ECHO OFF
chcp 65001
REM python -m venv venv
call venv\Scripts\activate.bat
REM pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple --upgrade -r requirements.txt
python run.py