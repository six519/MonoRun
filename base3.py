import sublime

class BaseMono3(object):

    @staticmethod
    def printMessage(msg):

        sublime.active_window().run_command('show_panel', {'panel': 'console', 'toggle': False})
        ascii_art = open("%s/%s" % (sublime.packages_path(), "/MonoRun/ascii"), 'r')
        print("%s" % (str(ascii_art.read()) % msg))
        
        ascii_art.close()