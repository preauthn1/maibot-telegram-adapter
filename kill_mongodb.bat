@echo off
echo 正在查找并结束所有 MongoDB 进程...
taskkill /F /IM mongod.exe
taskkill /F /IM mongo.exe
echo MongoDB 进程已结束
pause 