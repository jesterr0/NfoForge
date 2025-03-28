@echo off

echo Cleaning build... 
call make.bat clean 

echo Building HTML...
call make.bat html
