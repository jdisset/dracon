import os
import sys
import inspect
from contextlib import ContextDecorator, nullcontext
from typing import Any, Dict, Optional, Set, List, Callable
from dataclasses import dataclass

# color configuration
COLORS = {
    'RED': '\033[38;2;249;65;68m',
    'ORANGE': '\033[38;2;243;114;44m',
    'YELLOW_ORANGE': '\033[38;2;248;150;30m',
    'LIGHT_ORANGE': '\033[38;2;249;132;74m',
    'YELLOW': '\033[38;2;249;199;79m',
    'GREEN': '\033[38;2;144;190;109m',
    'TEAL': '\033[38;2;67;170;139m',
    'DARK_TEAL': '\033[38;2;77;144;142m',
    'BLUE_GREY': '\033[38;2;87;117;144m',
    'BLUE': '\033[38;2;39;125;161m',
    'GREY': '\033[90m',
    'RESET': '\033[0m',
}

# default configuration settings
DEFAULT_COLORS = {
    'line_number': COLORS['GREY'],
    'input': '',
    'input_name': COLORS['GREEN'],
    'output': '',
    'reset': COLORS['RESET'],
}

DEFAULT_GLYPHS = {
    'assign': '←',
    'create': '=',
    'return': '>',
}


# stream handling classes for output padding
class PaddedStdout:
    """Handles padded output stream with proper indentation."""

    def __init__(self, stream: Any, padding: str):
        if isinstance(stream, PaddedStdout):
            self.base_stream = stream.base_stream
            self.padding = stream.padding + padding
        else:
            self.base_stream = stream
            self.padding = padding
        self.buffer = ''

    def write(self, data: str) -> None:
        self.buffer += data
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            self.base_stream.write(self.padding + line + '\n')

    def flush(self) -> None:
        if self.buffer:
            self.base_stream.write(self.padding + self.buffer)
            self.buffer = ''
        self.base_stream.flush()


class pad_output(ContextDecorator):
    """Context manager for handling padded output."""

    def __init__(self, padding: str):
        self.padding = padding

    def __enter__(self):
        self._old_stdout = sys.stdout
        sys.stdout = PaddedStdout(sys.stdout, self.padding)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._old_stdout


@dataclass
class TraceConfig:
    """Configuration container for trace settings."""

    colors: Dict[str, str]
    glyphs: Dict[str, str]
    truncate_length: int
    preface_filename: bool
    inputs: bool
    output: bool
    watch: Optional[List[str]]
    name: Optional[str]

    @classmethod
    def create_default(cls, **kwargs):
        """Create trace configuration with default values."""
        config = cls(
            colors=DEFAULT_COLORS.copy(),
            glyphs=DEFAULT_GLYPHS.copy(),
            truncate_length=200,
            preface_filename=True,
            inputs=True,
            output=True,
            watch=None,
            name=None,
        )
        for key, value in kwargs.items():
            if hasattr(config, key):
                if key == 'colors' and value:
                    config.colors.update(value)
                elif key == 'glyphs' and value:
                    config.glyphs.update(value)
                else:
                    setattr(config, key, value)
        return config


class TracePrinter:
    """Handles all trace-related output formatting and printing."""

    def __init__(self, config: TraceConfig, func_color: str):
        self.config = config
        self.func_color = func_color
        # Padding with a vertical bar; note the trailing space.
        self.padding = f'{func_color}│ {COLORS["RESET"]}'

    def truncate(self, s: Any) -> str:
        """Truncate long strings with ellipsis in the middle."""
        s = str(s)
        lines = []
        for line in s.split('\n'):
            if len(line) > self.config.truncate_length:
                half = (self.config.truncate_length - 3) // 2
                out = line[:half] + '...' + line[-half:]
                lines.append(out)
            else:
                lines.append(line)
        return '\n'.join(lines)

    def print_function_entry(self, func_name: str, line_info: str) -> None:
        """Print function entry with proper formatting."""
        preface_str = (
            f"{self.config.colors['line_number']}@{line_info}{self.config.colors['reset']}"
            if self.config.preface_filename
            else ""
        )
        func_call_str = f"{self.func_color}┌ {func_name}{preface_str}{self.config.colors['reset']}("
        # Remove extra padding: if outermost, remove only one character (the extra space)
        if isinstance(sys.stdout, PaddedStdout):
            sys.stdout.write('\b\b')
        print(func_call_str)

    def print_arguments(self, bound_args: inspect.BoundArguments) -> Set[str]:
        """Print function arguments and return set of argument names."""
        arg_strings = []
        input_arg_names = set(bound_args.arguments.keys())

        for name, value in bound_args.arguments.items():
            arg_str = (
                f"{self.config.colors['input']}{self.truncate(value)}{self.config.colors['reset']}"
            )
            if '\n' in arg_str:
                print(f"{self.func_color}  {name} = {self.config.colors['reset']}")
                arg_str = arg_str.lstrip('\n')
                with pad_output("    "):
                    print(arg_str)
            else:
                arg_strings.append(
                    f"{self.func_color}  {name} = {self.config.colors['reset']}{arg_str}"
                )

        for arg_str in arg_strings:
            print(arg_str)
        print("):")
        return input_arg_names

    def print_variable_update(self, line_info: str, var: str, value: Any, is_new: bool) -> None:
        """Print variable updates with proper formatting."""
        glyph = self.config.glyphs['create'] if is_new else self.config.glyphs['assign']
        print(
            f"{self.config.colors['line_number']}{line_info}:{self.config.colors['reset']}"
            f"{var} {glyph} {self.truncate(value)}"
        )

    def print_function_exit(self, func_name: str, result: Any) -> None:
        """Print function exit with result."""
        if isinstance(sys.stdout, PaddedStdout):
            sys.stdout.write('\b\b')
        print(f"{self.func_color}└ {func_name}{self.config.colors['reset']} ")

        @pad_output(
            f"\b\b  {self.func_color}{self.config.glyphs['return']} {self.config.colors['reset']}"
        )
        def print_res():
            print(
                f"{self.config.colors['output']}{self.truncate(result)}{self.config.colors['reset']}"
            )

        print_res()


class TraceHandler:
    """Manages function tracing and variable watching."""

    def __init__(self, config: TraceConfig, printer: TracePrinter, input_arg_names: Set[str]):
        self.config = config
        self.printer = printer
        self.input_arg_names = input_arg_names
        self.watched_vars_prev = {}
        self.watching_all = config.watch is None
        if not self.watching_all and config.watch:
            for var in config.watch:
                self.watched_vars_prev[var] = None

    def handle_variable_updates(self, frame: Any, line_info: str) -> None:
        """Handle updates to watched variables."""
        local_vars = frame.f_locals
        vars_to_watch = local_vars.keys() if self.watching_all else self.config.watch

        for var in vars_to_watch:
            if var in local_vars:
                value = local_vars[var]
                prev_value = self.watched_vars_prev.get(var, '__UNINITIALIZED__')
                if prev_value == '__UNINITIALIZED__':
                    if var not in self.input_arg_names:
                        self.printer.print_variable_update(line_info, var, value, is_new=True)
                    self.watched_vars_prev[var] = value
                elif value != prev_value:
                    self.printer.print_variable_update(line_info, var, value, is_new=False)
                    self.watched_vars_prev[var] = value


def get_color_for_func(func_name: str) -> str:
    """Assign a consistent color to a function based on its name."""
    colors_list = [
        COLORS['RED'],
        COLORS['ORANGE'],
        COLORS['YELLOW_ORANGE'],
        COLORS['LIGHT_ORANGE'],
        COLORS['YELLOW'],
        COLORS['GREEN'],
        COLORS['TEAL'],
        COLORS['DARK_TEAL'],
        COLORS['BLUE_GREY'],
        COLORS['BLUE'],
    ]
    hash_value = sum(ord(c) for c in func_name) % len(colors_list)
    return colors_list[hash_value]


def get_source_info(func: Callable, frame: Optional[Any] = None) -> tuple:
    """Extract source file and line information."""
    filename = inspect.getsourcefile(func)
    filename = filename.split("/")[-1] if filename else "<unknown>"
    if frame:
        lineno = frame.f_lineno
        if frame.f_code.co_filename:
            filename = frame.f_code.co_filename.split("/")[-1]
    else:
        try:
            _, lineno = inspect.getsourcelines(func)
        except Exception:
            lineno = 0
    return filename, lineno


# Global counter for nested traced calls.
TRACE_DEPTH = 0


def ftrace(**kwargs):
    """
    A function decorator to trace execution, displaying inputs, outputs, and watched variables.

    parameters:
        inputs (bool): whether to show function inputs
        output (bool): whether to show function output
        watch (list): list of variable names to watch, or None for all
        preface_filename (bool): whether to show filename in trace
        colors (dict): custom colors for trace output
        glyphs (dict): custom glyphs for trace output
        truncate_length (int): maximum length for displayed values
        name (str): custom name for the traced function
    """
    if not os.getenv('ENABLE_FTRACE'):
        return lambda func: func

    config = TraceConfig.create_default(**kwargs)

    def decorator(func):
        func_color = get_color_for_func(func.__name__)
        printer = TracePrinter(config, func_color)

        def wrapper(*args, **kwargs):
            global TRACE_DEPTH
            # Always use padded output so that every traced call shows its vertical bar.
            with pad_output(printer.padding):
                TRACE_DEPTH += 1
                try:
                    func_class = (
                        f'{func.__qualname__.split(".")[0]}.'
                        if hasattr(func, '__qualname__') and '.' in func.__qualname__
                        else ''
                    )
                    func_name = f"{func_class}{func.__name__}"
                    call_frame = inspect.currentframe().f_back
                    filename, lineno = get_source_info(func, call_frame)
                    line_info = (
                        f"{filename}:l.{lineno}" if config.preface_filename else f"l.{lineno}"
                    )

                    # Print function entry and arguments.
                    printer.print_function_entry(func_name, line_info)
                    input_arg_names = set()
                    if config.inputs:
                        sig = inspect.signature(func)
                        bound_args = sig.bind(*args, **kwargs)
                        bound_args.apply_defaults()
                        input_arg_names = printer.print_arguments(bound_args)
                    else:
                        print(f"{func_name})")

                    # Set up tracing.
                    trace_handler = TraceHandler(config, printer, input_arg_names)

                    def local_trace(frame, event, arg):
                        if event == 'line':
                            _, lineno = get_source_info(func, frame)
                            li = (
                                f"{filename}:l.{lineno}"
                                if config.preface_filename
                                else f"l.{lineno}"
                            )
                            trace_handler.handle_variable_updates(frame, li)
                        return local_trace

                    def global_trace(frame, event, arg):
                        if event == 'call' and frame.f_code == func.__code__:
                            return local_trace
                        return None

                    sys.settrace(global_trace)
                    try:
                        result = func(*args, **kwargs)
                    finally:
                        sys.settrace(None)
                        if config.output:
                            printer.print_function_exit(func_name, result)
                    return result
                finally:
                    TRACE_DEPTH -= 1

        return wrapper

    return decorator
