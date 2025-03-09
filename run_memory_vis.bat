@echo on
chcp 65001 > nul 
set /p CONDA_ENV="请输入要激活的 conda 环境名称: "
call conda activate %CONDA_ENV%
if errorlevel 1 (
    echo 激活 conda 环境失败
    pause
    exit /b 1
)
echo Conda 环境 "%CONDA_ENV%" 激活成功
python src/plugins/memory_system/memory_manual_build.py
if errorlevel 1 (
    echo 命令执行失败，错误代码 %errorlevel%
    pause
    exit /b 1
)
echo 脚本成功完成
pause