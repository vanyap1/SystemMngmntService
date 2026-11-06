import time
import threading
import socket
from enum import Enum










class Main:
    def __init__(self, subClassImstance, subClassImstance2):
        self.subClassImstance = subClassImstance
        self.subClassImstance2 = subClassImstance2
        print("init class", self.subClassImstance.start())
        self.loop()

    def __repr__(self):
        print("report")

    def loop(self):
        while(True):
            time.sleep(1)
            print(self.subClassImstance.calc(100, 9))
            print(self.subClassImstance2.getVal("str2"))
            exampleStr = "Ivan Prints Python"
            cutData = exampleStr[3:10]
            
            print(">"+str(exampleStr.split(" ")).center(60)+"<")
            dig = 151
            print(f"val = {dig}")


    def main():
        print("test", 2<<5, "f>" , fn.fn1("123"))
        print(io["io2"][1])
        print(type(io))
        print(11//2) #результат - ціла частина після ділення
        print(11/2)
        print(11%2) #результат - остача після ділення
        print(2**6) #степінь


        print(var1 is var2) # перевірка ідентичності обєкта
        print(int(0xFE))
        print(max(arr))
        print(math.pi)
        print("OK" if var1==1 else "NOK")
        print(eval(exe))
        # Check single bit
        #allVals = 0
        #for i in range(255): 
        #    if(i>>io["io2"][1] & 1):
        #        print(bin(i))
        #        allVals+=1
        #print(allVals)
        return 0
    




class Subpoc:

    def __init__(self):
        #self.instance = instance
        print("Subpoc class init")
    def calc(self, x, y):
        return x+y    
    def start(self):
        return "startFN"
    
class Subproc2:

    def __init__(self, arg):
        self.arg = arg
        self.counter = 0
    def getVal(self, exampleStr):
        self.counter+=1
        return "arg = " + exampleStr , str(self.counter)



if __name__ == '__main__':
    inst = Subpoc()
    inst2 = Subproc2("somestring")
    Main(inst, inst2)