import sublime
import sublime_plugin
import subprocess
import re
import os
import threading
import Queue

MONO_TASK_NONE = 0
MONO_TASK_COMPILE = 1
MONO_TASK_COMPILE_DOTNET = 2
MONO_TASK_COMPILE_GTKSHARP = 3
MONO_TASK_EXECUTE = 4
MONO_TASK_TERMINATE = 5 

APP_OUT_ID = 'STOUT'
APP_ERR_ID = 'STERR'

def appRunnerCallback(application_id, message, got_error, return_code, *args, **kwargs):
    pass

class SyntaxErrorException(Exception):
    pass

class OtherErrorException(Exception):
    pass

class AppRunner(threading.Thread):

    applicationID = {}

    def __init__(self, *args, **kwargs):

        self.command_line = kwargs.pop('command_line')
        self.app_id = kwargs.pop('application_id')
        self.application_callback = kwargs.pop('application_callback', appRunnerCallback)
        self.application_args = kwargs.pop('application_args', tuple())
        self.application_kwargs = kwargs.pop('application_kwargs', dict())
        super(AppRunner, self).__init__(*args, **kwargs)

        self.queue = Queue.Queue()
        self.__gotError = False
        self.__app_message = []

        self.appRunning = subprocess.Popen(self.command_line, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False if isinstance(self.command_line,list) else True)

        self.outThread = threading.Thread(target=self.outputHandler, args=(APP_OUT_ID, self.appRunning.stdout))
        self.errThread = threading.Thread(target=self.outputHandler, args=(APP_ERR_ID, self.appRunning.stderr))


        if self.app_id in AppRunner.applicationID:
            AppRunner.applicationID[self.app_id].terminateApp()

        AppRunner.applicationID[self.app_id] = self

        self.outThread.start()
        self.errThread.start()
        self.start()

    @property
    def gotError(self):
        return self.__gotError

    @property
    def app_message(self):

        return self.__app_message

    def outputHandler(self, name, messages):

        for message in messages:
            self.queue.put((name, message))

        if not messages.closed:
            messages.close()

    def run(self):
        
        while True:
            
            try:
                qItem = self.queue.get(True, 1)

            except Queue.Empty:

                if self.appRunning.poll() is not None:
                    break
            else:

                name, message = qItem
                self.__app_message.append(message.strip())
                
                if name == APP_ERR_ID:
                    self.__gotError = True

        #self.application_callback(self.app_id, self.app_message, self.gotError, self.appRunning.returncode, *self.application_args, **self.application_kwargs)
        sublime.set_timeout(lambda : self.application_callback(self.app_id, self.app_message, self.gotError, self.appRunning.returncode, *self.application_args, **self.application_kwargs), 1000)
        if self.app_id in AppRunner.applicationID:
            del AppRunner.applicationID[self.app_id]

    def terminateApp(self):
        if self.app_id in AppRunner.applicationID:
            del AppRunner.applicationID[self.app_id]
        self.appRunning.kill()

def monoRunCallback(application_id, messages, got_error, return_code, *args, **kwargs):
    
    mono_task = kwargs.get('mono_task')
    splittedErr = []
    
    error_count = 0
    warning_count = 0
    compilation_message = ""
    line_errors = []
    line_message_errors = []
    marks = []

    if mono_task:
        #clear marks
        mono_task.view.run_command('clear_bookmarks', {'name':'mark'})
        if got_error:

            if return_code == 127:
                #invalid command
                MonoFunctions.printMessage("Please install mono on your system.")
            else:
                if application_id in range(1, 4):

                    for i, message in enumerate(messages):
                        if re.search('^Compilation failed', message):
                            #Compilation failed: 1 error(s), 0 warnings
                            compilation_message = message
                            message = re.sub('^[A-Z]:', '', message)
                            splittedErr = message.split(':')
                            splittedErr = splittedErr[1].split(',')
                            error_count = int(splittedErr[0].replace('error(s)','').strip())
                            warning_count = int(splittedErr[1].replace('warnings','').strip())
                        elif re.search('.error CS.', message):
                            message = re.sub('^[A-Z]:', '', message)
                            splittedErr = message.split(':')
                            errLine = int(splittedErr[0].split('(')[1].split(',')[0].strip())
                            line_message_errors.append("%s on line # %s." % (splittedErr[2].strip(), errLine))
                            line_errors.append(str(errLine))
                            mono_task.view.run_command('goto_line', {'line':errLine})
                            caretPos = mono_task.view.sel()[0].begin()
                            marks.append(mono_task.view.sel()[0])
                        elif re.search('^error CS',message):
                            message = re.sub('^[A-Z]:', '', message)
                            splittedErr = message.split(':')
                            line_message_errors.append("%s" % (splittedErr[1].strip()))
                        else:
                            line_message_errors.append("%s" % message)

                    if len(marks) > 0:
                        mono_task.view.add_regions("mark", marks, "mark", "dot")

                    MonoFunctions.printMessage("%s.\nPlease correct the dotted line(s).\nError on line(s): (%s).\n%s" % (compilation_message, ', '.join(line_errors), '\n'.join(line_message_errors)))
                else:
                    MonoFunctions.printMessage("An error occurred: %s" % "\n".join(messages))
        else:
            if application_id in range(1, 4):
                MonoFunctions.printMessage("Compilation successfull.")
            else:
                if len(messages) > 0:
                    MonoFunctions.printMessage("%s" % "\n".join(messages))
                else:
                    MonoFunctions.printMessage("Application terminated.")

class MonoFunctions(sublime_plugin.TextCommand):
    _task = MONO_TASK_NONE

    @staticmethod
    def printMessage(msg):

        sublime.active_window().run_command('show_panel', {'panel': 'console', 'toggle': False})
        ascii_art = open("%s/%s" % (sublime.packages_path(), "/MonoRun/ascii"), 'r')
        print "%s" % (ascii_art.read() % msg)
        ascii_art.close()

    def is_enabled(self):
        return False if MONO_TASK_EXECUTE in AppRunner.applicationID else True

    def run(self, edit):
        
        cmd = ""
        app = None

        try:

            if re.search('C#.tmLanguage$', self.view.settings().get('syntax')):
                
                if self.__class__._task == MONO_TASK_COMPILE:
                    #cmd = ["gmcs", self.view.file_name()]
                    cmd = "gmcs %s" % self.view.file_name()
                elif self.__class__._task == MONO_TASK_COMPILE_DOTNET:
                    cmd = "gmcs %s -pkg:dotnet" % self.view.file_name()
                elif self.__class__._task == MONO_TASK_COMPILE_GTKSHARP:
                    cmd = "gmcs %s -pkg:gtk-sharp-2.0" % self.view.file_name()
                elif self.__class__._task == MONO_TASK_EXECUTE:
                    cmd = "mono %s" % self.view.file_name().replace(".cs", ".exe")
                elif self.__class__._task == MONO_TASK_TERMINATE:
                    
                    #terminate
                    AppRunner.applicationID[MONO_TASK_EXECUTE].terminateApp()

                else:
                    raise Exception("Invalid mono functionality.")

                if self.__class__._task != MONO_TASK_TERMINATE:
                    app = AppRunner(command_line=cmd, application_id=self.__class__._task, application_callback=monoRunCallback, application_kwargs={'mono_task':self, 'mono_file':self.view.file_name()})

            else:
                try:
                    raise Exception("Invalid C# file (%s)." % os.path.basename(self.view.file_name()))
                except AttributeError:
                    pass

        except Exception as msg:
            MonoFunctions.printMessage("An unexpected error occurred while running the mono compiler.\nThe error is %s." % msg.message)

class MonoCompileCommand(MonoFunctions):
    _task = MONO_TASK_COMPILE

class MonoCompileDotNetCommand(MonoFunctions):
    _task = MONO_TASK_COMPILE_DOTNET

    def is_visible(self):
        return True if sublime.platform() == 'windows' else False

class MonoCompileGtkCommand(MonoFunctions):
    _task = MONO_TASK_COMPILE_GTKSHARP

    def is_visible(self):
        return True if sublime.platform() == 'linux' else False

class MonoRunCommand(MonoFunctions):
    _task = MONO_TASK_EXECUTE

class MonoTerminateApplicationCommand(MonoFunctions):
    _task = MONO_TASK_TERMINATE

    def is_enabled(self):
        return True if MONO_TASK_EXECUTE in AppRunner.applicationID else False

class MonoAboutCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        sublime.message_dialog('Created by: Ferdinand Silva (http://ferdinandsilva.com)')

