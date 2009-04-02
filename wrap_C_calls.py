#!/usr/bin/python
import os
import re

# struct handling could be removed, as there is actually no C function called from Fortran, with a struct in its signature

class WrapperException:
    def __init__(self,message):
        self.message = message
    def printout(self):
        print self.message

class CFunction:
    def __init__(self,name,returnType,args,sourceFile):
        self.name = name
        self.returnType = returnType
        self.args = args # a list of (type, pointerFlag, varname) triplets
        self.sourceFile = sourceFile

class Wrapper:
    def collectCfuncCalledByFortran(self):
        cFiles = self.collectFiles('C')
        cFunctions = []
        for file in cFiles:
            f = open(file,'r')
            lines = f.readlines()
            # preprocessing: remove all comments
            newLines = []
            for line in lines:
                m = re.match(r'^[\s\t]*//',line)
                if m:
                    skip = True
                    
            for line in lines:
                m = re.match(r'^[\s\t]*(void|int|float|double)[\s\t]*(\*)?[\s\t]+([\w\d_]+)[\s\t]*\(([\*\w\d,\s]*)\)',line)
                if m:
                    #print "function found:"+line
                    returnType = m.group(1)
                    returnPointer = m.group(2)
                    name = m.group(3)
                    #print "function found of type:"+returnType
                    #print "function found of name:"+name                    
                    args = [] # a list of (type, varname) couples
                    compoundArgs = m.group(4)
                    #print "function found with arg list:"+compoundArgs
                    # now split the compound args
                    argDeclarations = compoundArgs.split(",")
                    for argDeclaration in argDeclarations:
                        argDeclaration = argDeclaration.strip() # remove heading and trailing blanks
                        if not argDeclaration == '':
                            #print "now trying to match '"+argDeclaration+"'"
                            pattern = r'(const)?[\s\t]*(struct)?[\s\t]*([\w\d_]+)[\s\t]*(\*)?[\s\t]*([\w\d_]+)'
                            match = re.match(pattern,argDeclaration)
                            if match:
                                if match.group(1) == 'const':
                                    argConstFlag = True
                                else:
                                    argConstFlag = False
                                if match.group(2) == 'struct':
                                    argStructFlag = True
                                else:
                                    argStructFlag = False
                                argType = match.group(3)
                                if match.group(4)=='*':
                                    argPointerFlag = True
                                else:
                                    argPointerFlag = False
                                argName = match.group(5)
                            else:
                                raise WrapperException("failed to match argument declaration:"\
                                                       +argDeclaration\
                                                       +" in "+compoundArgs)
                            args.append([argName, argConstFlag, argStructFlag, argPointerFlag, argType])
                    #for i in range(3:m.groups+1):
                    #    args = m.group(i), m.group(i+1)
                    func = CFunction(name,returnType,args,file)
                    cFunctions.append(func)
                    
        # now check wether the collected functions are called by Fortran
        fortranFiles = self.collectFiles('Fortran')
        
        # register all pure Fortran subroutines as we don't want to mix them with calls from Fortran to C
        fortranSubroutines = []
        for file in fortranFiles:
            f = open(file,'r')
            lines = f.readlines()
            for line in lines:
                m = re.match('^[\s\t]*subroutine[\s\t]+(\w+)\(',line)
                if m:
                    subroutine = m.group(1)
                    fortranSubroutines.append(subroutine)

        self.fortranCalls = [] # an instance variable that must be initialized here
        for file in fortranFiles:
            f = open(file,'r')
            lines = f.readlines()
            for line in lines:
                m = re.match('[\s\t]*call[\s\t]+(\w+)\(([\w\s\d,]*)\)',line)
                if m:
                    name = m.group(1)
                    # print "Fortran call: "+name
                    for func in cFunctions:
                        # as Fortran is case insensitive, the strings must be compared as lower case
                        if func.name.lower() == name.lower():
                            # first make sure that the function is not a Fortran subroutine
                            # then check that the number and type of parameters match...
                            if not func.name in fortranSubroutines:                           
                                # print "C function "+name+" is called from Fortran"
                                alreadyPresent = False # default
                                for anotherFunc in self.fortranCalls:
                                    if anotherFunc.name == func.name:
                                        alreadyPresent = True
                                if not alreadyPresent:
                                    self.fortranCalls.append(func)
                            #if func not in self.fortranCalls: # only add a function once in the list
                            #    self.fortranCalls.append(func)

    
    def listFunctionsCalledByFortran(self):
        for func in self.fortranCalls:
            # recompose compound arg string:
            argStr = ''
            for arg in func.args:
                [varName, varConstFlag, varStructFlag, varPointerFlag, varType] = arg
                argStr = argStr + varType + ' ' + varName
                if not arg == func.args[-1]: # not the last element in list
                    argStr = argStr + ','
            # print "Fortran calls C function: " + func.returnType +' ' + func.name + "(" + argStr + ")"

    def generateWrapperCode(self):
        f = open("c_wrappers.c","w")
        header = []
        code = []
        nFunc = len(self.fortranCalls)
        header.append('/* set of '+str(nFunc)+' wrappers to synchronize FORTRAN and C stdout buffers */\n')
        header.append('/* when crossing the border upon calling C from FORTRAN. */\n\n')
        header.append('#include <stdio.h>\n\n')
        header.append('#include "c_prototypes.h"\n\n') # prototypes
        for func in self.fortranCalls:
            # recompose compound arg string:
            argStr = '' # together with their types, for the signature
            argList = '' # without their types, as passed at invocation
            structures = [] # the list of structures that should be defined externally
            for arg in func.args:
                [varName, varConstFlag, varStructFlag, varPointerFlag, varType] = arg
                if varConstFlag == True:
                    constStr = 'const '
                else:
                    constStr = ''
                if varStructFlag == True:
                    structStr = 'struct '
                    structures.append(varType)
                else:
                    structStr = ''
                if varPointerFlag == True:
                    argStr = argStr + constStr + structStr + varType + '* ' + varName                  
                else:
                    argStr = argStr + constStr + structStr + varType + ' ' + varName
                argList = argList + varName                
                if not arg == func.args[-1]: # not the last element in list
                    argStr = argStr + ','
                    argList = argList + ','
            code.append("/* Wrap '"+func.name+"' defined in '"+func.sourceFile+"' */\n")
            newSignature = func.returnType+' '+func.name+'_('+argStr+'){\n' # min the '_' !!!
            code.append(newSignature)
            # code.append('printf("WRAPPER: now returning from invocation of '+func.name+'\\n");\n')
            debugMsg = '' # otherwise could be func.name
            code.append('\tcall_fortran_flush_("'+debugMsg+'",'+str(len(debugMsg))+');\n')
            body = '\t' +func.name+'_wrapped('+argList+');\n' # should return a void (to be checked later on)
            code.append(body)
            code.append('\tfflush(stdout);\n')
            code.append('}\n\n')
        for struct in structures:
            header.append('extern struct '+struct+';\n')
            if struct == structures[-1]: # last one
                header.append('\n')
        f.writelines(header)
        f.writelines(code)
        f.close()

    def generateWrapperHeader(self):
        f = open("c_wrappers.h","w")
        code = []
        code.append('#ifndef _C_WRAPPERS_H\n')
        code.append('#define _C_WRAPPERS_H\n')
        code.append('/* redirect C calls to wrapped functions that synchronize FORTRAN and C sdout buffering */\n')
        code.append('/* when crossing the border upon calling C from FORTRAN*/\n\n')
        code.append('#include "c_wrappers_prototypes.h"\n')
        # at this stage should probably include the equivalent of fortran_wrappers_prototypes.h
        for func in self.fortranCalls:
            line = '#define '+ func.name+"_" + ' '  + func.name + "_wrapped\n" # mind the '_' !!!
            code.append(line)
        code.append('#endif\n')
        f.writelines(code)
        f.close()

    def generateWrapperPrototypes(self):
        f = open("c_wrappers_prototypes.h","w")
        header = []
        code = []
        header.append('/* to avoid conflicting implicit declarations from code calling functions below*/\n')
        header.append('#ifndef _C_WRAPPERS_PROTOTYPES_H\n')
        header.append('#define _C_WRAPPERS_PROTOTYPES_H\n')
        structures = [] # struct defined externally
        for func in self.fortranCalls:
            argStr = '' # type, varname
            for arg in func.args:
                [varName, varConstFlag, varStructFlag, varPointerFlag, varType] = arg
                if varConstFlag == True:
                    constStr = 'const '
                else:
                    constStr = ''
                if varStructFlag == True:
                    structStr = 'struct '
                    structures.append(varType) # the struct
                else:
                    structStr = ''
                if varPointerFlag == True:
                    argStr = argStr + constStr + structStr + varType + '* '+ varName
                else:
                    argStr = argStr + constStr + structStr + varType + ' ' + varName
                if not arg == func.args[-1]: # not the last element in list
                    argStr = argStr + ','
            code.append("/* Wrap '"+func.name+" defined in '"+func.sourceFile+"' */\n")
            signature = func.returnType+' '+func.name+'_wrapped('+argStr+');\n'
            code.append(signature)
        code.append('#endif\n')
        #for struct in structures:
        #    header.append('extern struct '+struct+';\n')
        #    if struct == structures[-1]: # last one
        #        header.append('\n')
        #header.append('#include "madx.h"\n') # as the above does not work in C - struct in_cmd and table now known
        f.writelines(header)
        f.writelines(code)
        f.close()
        
    def generatePrototypes(self): # this function could easily be combined with generateWrapperPrototypes as they share most of code
        f = open("c_prototypes.h","w")
        header = []
        code = []
        header.append('/* to avoid warnings of implicit declarations from c_wrappers.c */\n')
        header.append('#ifndef C_PROTOTYPES_H\n')
        header.append('#define C_PROTOTYPES_H\n')
        structures = [] # struct defined externally
        for func in self.fortranCalls:
            argStr = '' # type, varname
            for arg in func.args:
                [varName, varConstFlag, varStructFlag, varPointerFlag, varType] = arg
                if varConstFlag == True:
                    constStr = 'const '
                else:
                    constStr = ''
                if varStructFlag == True:
                    structStr = 'struct '
                    structures.append(varType) # the struct
                else:
                    structStr = ''
                if varPointerFlag == True:
                    pointerStr = '* '
                else:
                    pointerStr = ''
                argStr = argStr + constStr + structStr + varType + pointerStr + varName
                if not arg == func.args[-1]: # not the last element in the list
                    argStr = argStr + ','
            code.append("/* Wrap '"+func.name+" defined in '"+func.sourceFile+"' */\n")
            signature = func.returnType + ' ' + func.name + '_' + '(' + argStr + ');\n'
            code.append(signature)
        code.append('#endif\n')
        #for struct in structures:
        #    header.append('extern struct '+ struct+';\n')
        #    if struct == structures[-1]: # last one
        #        header.append('\n')
        #header.append('#include "madx.h"\n') # as the above does not work in C - struct in_cmd and tables now known
        f.writelines(header)
        f.writelines(code)
        f.close()
        

    def collectFiles(self,type):
        if type == 'C':
            suffix = 'c'
        elif type == 'Fortran':
            suffix = 'f90'
        # until we can rely on the subprocess library from Python 2.5 ...
        # no way to get the output of a system call but through a file
        command = 'ls -l *.' + suffix + ' > files.out'
        os.system(command)
        f = open("files.out",'r')
        lines = f.readlines()
        files = []
        for line in lines:
            m = re.match(r'.+[\s\t]+([\w\.]+)[\s\t]*$',line)
            if m:
                file = m.group(1)
                #print("found file '"+file+"'")
                files.append(file)
        os.system('rm files.out') # clean-up
        return files

def wrapFortranCallingC():
    try:
        wrapper = Wrapper()
        wrapper.collectCfuncCalledByFortran()
        wrapper.listFunctionsCalledByFortran()
        wrapper.generateWrapperCode()
        wrapper.generateWrapperHeader()
        wrapper.generateWrapperPrototypes()
        wrapper.generatePrototypes()
        # print("Completed.")
    except WrapperException, we: # from Python 2.6, should restate as 'except WrapperException as we:'
        we.printout()
        
if __name__ == "__main__":
    wrapFortranCallingC()
