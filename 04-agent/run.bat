@echo off
REM 双击此文件启动 AgentEvanescia（xAgent）
REM 会在当前目录打开命令行窗口，并以该目录为项目根
REM 注意：.mcp.json 和 .agents/skills/ 都相对于启动目录

cd /d "%~dp0"
echo AgentEvanescia 启动中...
echo 项目根目录: %cd%
echo.
python main.py
pause
