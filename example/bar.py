from foo import FooInterpreter

class BarInterpreter(FooInterpreter):
    name        = 'bar'

    def do_helloworld(self, args):
        return "Hello, bar!"
