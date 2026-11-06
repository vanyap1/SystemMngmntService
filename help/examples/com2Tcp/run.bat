@echo off
com2tcp --baud 9600 --ignore-dsr --telnet \\.\COM4 12345
