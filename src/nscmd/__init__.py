"""
This library is loosely based off of the 'cmd' library. It started
after I found myself trying to hack namespaces into cmd.py and causing
a lot more code bloat than what was really necessary.

You can find the original cmd library here:
https://github.com/python/cpython/blob/main/Lib/cmd.py

- ropbear
"""

import os
import sys
import random
import inspect
import readline
from datetime import datetime
import logging
from textwrap import wrap

TITLE = __name__

BANNER = """
\033[%s;%sm
███╗   ██╗███████╗ ██████╗███╗   ███╗██████╗ 
████╗  ██║██╔════╝██╔════╝████╗ ████║██╔══██╗
██╔██╗ ██║███████╗██║     ██╔████╔██║██║  ██║
██║╚██╗██║╚════██║██║     ██║╚██╔╝██║██║  ██║
██║ ╚████║███████║╚██████╗██║ ╚═╝ ██║██████╔╝
╚═╝  ╚═══╝╚══════╝ ╚═════╝╚═╝     ╚═╝╚═════╝ 
\033[0m                              
Welcome to %s
%s
""" % (
    random.choice('01'),
    random.choice([str(x) for x in range(30,38)]),
    TITLE,
    datetime.now()
)

PROMPT = '\n\033[%s;%sm└─▪\033[0m' % (
    random.choice('01'),
    random.choice([str(x) for x in range(30,38)]),
)

# Delimeters
CMD_DELIM       = " "
LINE_DELIM      = "\n"
NS_DELIM        = "."
COMPLETE_KEY    = "tab"

# Help output
HELP_WIDTH      = 60
HELP_CMD_DELIM  = "\t"
HELP_BORDER_CHR = "#"
HELP_TOPIC      = HELP_BORDER_CHR * 4 + " %s "
HELP_END        = "\n\n"

# Logging
LOG_LEVEL   = logging.INFO
logging.basicConfig(level=LOG_LEVEL)

# Input/Ouput methods, set for binary arithmetic
METHOD_STD      = 1
METHOD_FILE     = 2
METHOD_STR      = 4
METHOD_LIST     = 8

# global IO queues for input/output handling
inqueue = []
outqueue = []

# global namespace state and map, the focal points of this library
NS_STATE = ('', None) # (ns, obj)
NS_MAP = {}

class MainInterpreter:
    name            = 'main'
    namespace       = name
    prefix_cmd      = "do_"
    prefix_help     = "help_"
    log             = logging.getLogger(namespace)
    global_cmds     = ['quit','exit','help','clear']

    def __clear_globals(self):
        """Clear critical global variables"""
        global inqueue, outqueue, NS_STATE, NS_MAP
        inqueue = outqueue = []
        NS_STATE = ('', None)
        NS_MAP = {}

    def __init__(self, cmd_in=None, cmd_out=None, outfile=None):
        """
        MainInterpreter
        Acts as the main or root namespace for the nscmd TUI.

        @param cmd_in: An optional initialization parameter specifying where to read
                      commands from. Defaults to input().
        @param cmd_out: An optional initialization parameter specifying where to write
                       the output of commands to. Multiple methods can be specified.
                       Defaults to sys.stdout.
        @param outfile: An optional initialization parameter specifying a file to
                       append the output of commands to.
        @return: Initialized MainInterpreter object
        """
        self.__clear_globals()
        global inqueue, outqueue
        
        # choose the method of input based on the type of 'cmd_in'
        self.method_in, inqueue = self.__choose_method_in(cmd_in)

        # choose the method of output based on the type of 'cmd_out' 
        self.method_out, self.outstr, self.outfile = self.__choose_method_out(cmd_out, outfile)

        # default NS_STATE to the main namespace, init NS_MAP globally
        global NS_STATE, NS_MAP
        NS_STATE = (MainInterpreter.namespace, self)
        NS_MAP = self.__init_namespaces()
        self.log.debug(f"Namespace Map: {NS_MAP}")


    def __choose_method_in(self, cmd_in):
        """
        Selects the input method based on the parameters passed to __init__().

        @param cmd_in: An ambiguous parameter which specifies where commands may be read from
        @return: Tuple of form (<input_method_flag>, <filled_input_command_queue>)
        """
        method_in = None
        inqueue = []
        cmds = None

        if cmd_in is None:
            method_in = METHOD_STD

        elif type(cmd_in) == str:
            # a str can either be a file path or string of commands
            if os.path.exists(cmd_in):
                self.log.info(f"Reading commands from file '{cmd_in}'")
                with open(cmd_in,"r") as f:
                    lines = f.readlines()
                cmds = [l.strip() for l in lines]
                method_in = METHOD_FILE
            else:
                self.log.warning(f"No path found, assuming command input string")
                cmds = [l.strip() for l in cmd_in.split(LINE_DELIM)]
                method_in = METHOD_STR

        elif type(cmd_in) == list:
            self.log.info(f"Adding {len(cmd_in)} commands from command input list")
            cmds = cmd_in
            method_in = METHOD_LIST

        else:
            self.log.error(f"Unsupported command input type: {type(cmd_in)}, defaulting to METHOD_STD")
            method_in = METHOD_STD

        if cmds is not None:
            cmds.reverse() # reverse to make FIFO
            inqueue = cmds
        
        return (method_in, inqueue)


    def __choose_method_out(self, cmd_out, outfile):
        """
        Selects the output method based on the parameters passed to __init__().

        @param cmd_out: a string to append output to if METHOD_STR is set
        @param outfile: a file to append output to if METHOD_FILE is set
        @return: Tuple of form (<output_method_flag>, <output_str>, <output_file>)
        """
        method_out = None
        output_tgt = None

        if cmd_out is None:
            # default to sys.stdout
            method_out = METHOD_STD

        if type(cmd_out) == str:
            self.log.warning(f"No path '{cmd_out}' found, assuming command output string")
            method_out = METHOD_STR
            output_tgt = cmd_out

        elif type(cmd_out) == list:
            method_out = METHOD_LIST

        elif cmd_out is not None:
            self.log.error(f"Unsupported command output type: {type(cmd_out)}, defaulting to sys.stdout")
            method_out = METHOD_STD

        if outfile is not None:
            if method_out is None:
                method_out = METHOD_FILE
            else:
                method_out += METHOD_FILE
            outfile = outfile

        return (method_out, output_tgt, outfile)


    def __cmd_read(self, prompt=False):
        """
        Read one command from the predetermined command input.
        
        @global inqueue: The input queue built on startup of the interpreter, used for automated input
        @param prompt: Whether or not to include a prompt with input()
        @return: A string representing a single user command or None if no command entered (empty line)
        """
        global inqueue
        ns, obj = NS_STATE
        self.log.debug(f"Popping command from inqueue: {inqueue}")
        
        if METHOD_STD & self.method_in:
            return input(ns + PROMPT)

        else:
            if inqueue == []:
                return None
            return inqueue.pop()


    def __cmd_output(self,data):
        """
        Write results to the predetermined command output.
        Note that METHOD_LIST is always in effect due to the outqueue

        @global outqueue: All output of commands, regardless of output type.
        @param data: The data returned from executing the command
        @return: None
        """
        global outqueue
        
        if METHOD_STD & self.method_out:
            self.log.debug("Using output method METHOD_STD")
            sys.stdout.write(data + LINE_DELIM)

        if METHOD_STR & self.method_out:
            self.log.debug("Using output method METHOD_STR")
            self.outstr += data + LINE_DELIM

        if METHOD_FILE & self.method_out:
            self.log.debug("Using output method METHOD_FILE")
            with open(self.outfile, "a") as f:
                f.write(data + LINE_DELIM)
        
        outqueue.append(data)
        self.log.debug(f"Pushed to outqueue: {outqueue}")


    def __init_namespaces(self):
        """
        Starting with the main namespace (MainInterpreter), build out the
        namespaces as defined by the inheritence tree. The SubInterpreter
        class will be skipped since it is only meant to be a template and
        should not show up in commands.

        @return: A dictionary object with the namespace as a key and an
                instantiated object for that namespace as the value.
        """
        def create_namespace(obj):
            """
            Use getmro() from the inspect library to get an ordered inheritance list

            @param obj: A python class (not an object)
            @return: A List object of the inheritance tree for the class, starting with
                    the MainInterpreter class.
            """
            bases = list(inspect.getmro(obj))
            
            # getmro() returns starting with the class itself first, but a namespace should
            # be top to bottom instead
            bases.reverse()
            self.log.debug(f"Built class list for {obj.name}: {bases}")

            # SubInterpreter is only a template, do not include in namespace
            bases.remove(SubInterpreter)
            
            # getmro() returns the Python built-in 'object' class as well
            bases.remove(object)

            nslist = [nsclass.name for nsclass in bases]
            return NS_DELIM.join(nslist)

        # Namespace Map
        def create_nsmap(obj):
            """
            Recursive function to create a List of dictionaries to be added to
            the namespace map.

            @param obj: A class that has SubInterpreter as the root of it's family tree
            @return: A dictionary with the namespace as the key and the respective
                    instantiated object as the value.
            """
            instance = obj()
            instance.namespace = create_namespace(obj)
            self.log.debug(f"Built namespace for {obj.name}: {instance.namespace}")
            
            # if no subclasses, there's no more sub namespaces to iterate
            if obj.__subclasses__() == []:
                return {instance.namespace:instance}

            # recursively iterate through sub namespaces
            current_ns = {instance.namespace:instance}
            [current_ns.update(create_nsmap(ns)) for ns in obj.__subclasses__()]
            return current_ns

        # The nsmap variable is a dictionary with namespace strings as keys 
        # and instantiated objects as values. It might seem that a n-ary tree
        # would be the better choice, but it's easier to handle the namespaces
        # as key strings.
        nsmap = {
            self.namespace:self,
        }

        # skip SubInterpreter since it's just a template
        for ns in SubInterpreter.__subclasses__():
            nsmap.update(create_nsmap(ns))
        return nsmap


    def __get_subs_of_ns(self, search_ns, depth=None):
        """
        Function to gather the sub-namespaces of a given namespace.

        @param search_ns: the namespace to gather sub-namespaces from
        @param (optional) depth: how generations of sub-namespaces to include
        @return: A Set object of sub-namespaces in NS_DELIM notation
        """
        subs = []
        search_ns_len = len(search_ns)
        for ns in NS_MAP.keys():
            if ns[0:search_ns_len] == search_ns:
                branch = ns[search_ns_len+len(NS_DELIM):]
                depths = branch.split(NS_DELIM)
                if depth is not None and type(depth) == int:
                    subs.append(NS_DELIM.join(depths[0:depth]))
                else:
                    subs.append(NS_DELIM.join(depths))
        return set(subs)

    def __get_cmds_of_ns(self, search_ns):
        """
        Function to gather all of the commands of a namespace
        based on prefix_cmd

        @param search_ns: the namespace to gather commands from
        @return: A List object of functions that match the 
                prefix_cmd + cmd format.
        """
        obj_methods = dir(NS_MAP[search_ns].__class__)
        funcs = []
        for func in obj_methods:
            if func[0:len(self.prefix_cmd)] == self.prefix_cmd:
                funcs.append(func[len(self.prefix_cmd):])
        return funcs

    def empty(self):
        """
        Handler for empty user input command

        @return: None
        """
        return None

    def default(self, cmd, args):
        """
        Default handler for non-empty but otherwise unhandled user input command.

        @return: None
        """
        self.log.error(f"Unknown command '{CMD_DELIM.join([cmd]+args)}'")
        return None


    def default_complete(self, text):
        """
        Default behavior for command completion.

        @return: Empty list
        """
        return []


    def __complete_options(self, text, state):
        """
        Function used by the 'readline' library to complete the command input.
        This is built specifically for completion with namespaces as well
        as the methods within the namespace the typed command would be at if
        the namespace was changed to it with __set_namespace.

        @param text: a string representing the input text needing completion
        @param state: the offset from the 'readline' begidx the 'text' param is at
        @return: A List object of potential completions given the current text & state
        """
        if NS_MAP is None or NS_MAP == {}:
            return []

        # try to see if we are in a namespace based on the entered text
        lb = readline.get_line_buffer().lstrip()
        search_ns, obj, args = self.__check_namespace(lb.split(CMD_DELIM))

        # we always want main to be an option if it's the start of the line
        begidx = readline.get_begidx()
        main = []
        if begidx == 0 and MainInterpreter.name[:len(text)] == text:
            main = [MainInterpreter.name]

        funcs = []
        if args != []:
            funcname = self.prefix_cmd + text
            all_funcs = self.__get_cmds_of_ns(search_ns)
            funcs = [func for func in all_funcs if func.startswith(funcname)]
                    
        subs = set()
        for sub in self.__get_subs_of_ns(search_ns):
            if sub[:len(text)] == text:
                subs.add(ns[search_ns_len+len(NS_DELIM):].split(NS_DELIM)[0])
        self.log.debug(f"subs: {subs}")
        self.log.debug(f"funcs: {funcs}")

        return main + subs + funcs


    def __complete(self, text, state):
        """
        Returns the next possible command based off of the 'text' parameter.

        @param text: Current input text
        @param state: Completer state
        @return: Current state index if something found, otherwise none
        """
        line = readline.get_line_buffer().lstrip()

        self.completion_matches = self.__complete_options(text, state)
        self.log.debug(f"completion_matches: {self.completion_matches}")
        try:
            return self.completion_matches[state]
        except IndexError:
            return None


    def __check_namespace(self, parts):
        """
        This function searches the current namespace followed by the main (root)
        namespace to see if the command entered fits in either location. This function
        determines order of precedent, meaning commands in the current namespace
        will take precedent over ones with the same name under the main namespace.

        @param parts: The command broken up into List object based on CMD_DELIM
        @return: Tuple object of form (<namespace_name>,<namespace_obj>,<remaining_parts_of_cmd>)
        """
        
        i = 0                       # index of command being checked against namespaces
        current_ns = NS_STATE[0]    # current namespace string
        last_valid = None           # last valid namespace found
        args = []                   # remaining arguments from command string

        # check the current namespace for new ns
        for i in range(len(parts)):
            test_ns = NS_DELIM.join(parts[0:i+1])
            tmp_ns = current_ns + NS_DELIM + test_ns
            self.log.debug(f"Current ns search: tmp_ns = {tmp_ns}")
            if tmp_ns in NS_MAP.keys():
                last_valid = tmp_ns
                args = parts[i+1:]
            else:
                break
        
        # if no sub ns found, check from root (main) namespace
        if last_valid == None:
            for i in range(len(parts)):
                test_ns = NS_DELIM.join(parts[0:i+1])
                self.log.debug(f"Root ns search: test_ns = {test_ns}")
                if test_ns in NS_MAP.keys():
                    last_valid = test_ns
                    args = parts[i+1:]
                else:
                    break
        
        # invalid namespace, stay in current namespace
        if last_valid == None:
            args = parts[i:]
            return (NS_STATE[0], NS_STATE[1], args)
        
        return (last_valid, NS_MAP[last_valid], args)


    def __set_namespace(self, parts):
        """
        This function sets the namespace based on the users input
        for proper execution context.

        @global NS_STATE: The namespace state Tuple, which this function will alter
        @param parts: A List object containing the user input command
        @return: A List object containing remaining arguments
                after the namespace has been parsed
        """
        global NS_STATE

        ns, obj, parts = self.__check_namespace(parts)
        self.log.debug(f"__check_namespace() returned ns:{ns} | obj:{obj} | parts:{parts}")

        self.log.debug(f"Entering namespace state (NS_STATE) {ns}")
        NS_STATE = (ns, obj)
        return parts   


    def __exec(self, cmd, args, prefix=None):
        """
        Executes a method of the class based off the user input command
        and the prefix_cmd string.

        @param cmd: A string of the command to execute.
        @param args: A List object containing the command args, split on CMD_DELIM
        @param prefix: Used when passing a special prefix such as 'help_'
        @return: The result of the called function
        """
        prefix = self.prefix_cmd if prefix is None else prefix
        try:
            self.log.debug(f"Attempting getattr on {self} for {prefix + cmd}")
            func = getattr(self, prefix + cmd)
        except AttributeError:
            # only return default for prefix_cmd
            return self.default(cmd, args) if prefix is None else None
        return func(args)


    def __cmd_parse(self, data):
        """
        The function to parse the user input command string.

        @global NS_STATE: The global namespace state, which is saved and restored
                         if no arguments are passed with the command
        @param data: A raw user input command string
        @return: The result of the target function, otherwise None
        """
        global NS_STATE

        parts = [part.strip() for part in data.split(CMD_DELIM)]
        if '' in parts:
            parts.remove('')
        self.log.debug(f"Split command: {parts}")

        if parts == []:
            return self.empty()

        self.log.debug(f"Pre-exec NS_STATE: {NS_STATE}")
        saved_ns_state = NS_STATE

        remaining_parts = self.__set_namespace(parts)

        if remaining_parts != []:
            # if arguments were passed, exec in new namespace
            # and then return to the original state
            args = remaining_parts[1:] if len(remaining_parts) > 1 else []
            result = NS_STATE[1].__exec(remaining_parts[0], args)
            NS_STATE = saved_ns_state
        else:
            # if there were no arguments passed, remain in the new namespace
            result = None

        self.log.debug(f"Post-command NS_STATE: {NS_STATE}")

        return result

    def __banner(self):
        """Print the banner to sys.stdout"""
        sys.stdout.write(BANNER)


    def run(self, prompt=False):
        """
        Handles the input, execute, output loop.

        @param prompt: A boolean which, if true, prints the prompt each loop.
        @return: None
        """

        # set complete function
        readline.parse_and_bind(f"{COMPLETE_KEY}: complete")
        readline.set_completer(self.__complete)

        data_in = ""
        while data_in != None:
            self.log.debug(f"Running in context of {self}")

            try:
                # handle input
                data_in = self.__cmd_read(prompt=prompt)
                if data_in == None:
                    break

                # parse, set namespace, exec
                data_out = self.__cmd_parse(data_in)
                
                # handle output
                if data_out is not None:
                    self.__cmd_output(data_out)

            except KeyboardInterrupt:
                data_in = None

    def tui(self):
        """
        Prints the banner and sets the prompt boolean for run().

        @return: None
        """
        self.__banner()
        self.run(prompt=True)

    def default_help(self):
        """
        Function to handle the 'help' command with no input.

        @return: None
        """

        # global commands first
        topic = "Global Commands"
        helpstr_global = (HELP_TOPIC % topic)
        helpstr_global += HELP_BORDER_CHR*(HELP_WIDTH - len(helpstr_global)) +"\n"
        helpstr_global += "\n".join(wrap(HELP_CMD_DELIM.join(self.global_cmds), width=HELP_WIDTH)) + "\n"
        
        # sub-namespaces of current namespace
        subs = list(self.__get_subs_of_ns(NS_STATE[0], depth=1))
        subs.remove('')
        topic = "Sub-namespaces"
        helpstr_subs = (HELP_TOPIC % topic)
        helpstr_subs += HELP_BORDER_CHR*(HELP_WIDTH - len(helpstr_subs)) +"\n"
        helpstr_subs += "\n".join(wrap(HELP_CMD_DELIM.join(subs), width=HELP_WIDTH)) + "\n"

        # commands in current namespace
        funcs = self.__get_cmds_of_ns(NS_STATE[0])
        [funcs.remove(x) for x in self.global_cmds]
        topic = "Current Namespace Commands"
        helpstr_cmds = (HELP_TOPIC % topic)
        helpstr_cmds += HELP_BORDER_CHR*(HELP_WIDTH - len(helpstr_cmds)) +"\n"
        helpstr_cmds += "\n".join(wrap(HELP_CMD_DELIM.join(funcs), width=HELP_WIDTH)) + "\n"

        helpstr = helpstr_global + helpstr_subs + helpstr_cmds + HELP_END
        self.__cmd_output(helpstr)


    def do_help(self, args):
        """
        Global help command. This will attempt to execute a 'help' command
        in the current namespace via the 'prefix_help' notation. If you write
        your own help function, you MUST return something other than None in
        order to skip the search for a docstring and other default behavior.

        This function utilizes NS_MAP[MainInterpreter.namespace] to ensure
        the correct functions are executed for default behavior and output.

        @param args: A List object of the arguments passed to the help command
        @return: None
        """
        if args != []:
            arg = args[0]
        else:
            return NS_MAP[MainInterpreter.namespace].default_help()

        notfound = "No help available for %s"
        
        # attempt to execute with prefix_help
        result = self.__exec(arg, [], prefix=self.prefix_help)
        self.log.debug(f"self.__exec() returned {result}")

        # otherwise use docstring, print an error if bogus help target
        if result is None:
            try:
                # search for command docstring
                docstr = getattr(self, self.prefix_cmd + arg).__doc__
                if docstr is not None:
                    NS_MAP[MainInterpreter.namespace].__cmd_output(docstr)
            except AttributeError:
                NS_MAP[MainInterpreter.namespace].__cmd_output(notfound % arg)

    def do_quit(self, args):
        """Global command to quit program"""
        sys.exit(0)
    
    def do_exit(self, args):
        """Global command to exit program"""
        self.do_quit(args)

    def do_clear(self, args):
        """Global command to clear terminal"""
        os.system("clear")


class SubInterpreter(MainInterpreter):
    name            = None
    intro           = None

    def __init__(self):
        self.log = logging.getLogger(self.namespace)
