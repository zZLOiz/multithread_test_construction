#! /usr/bin/env python
# encoding: utf-8

import os
import json

from waflib import Options, Scripting, Logs
from waflib.Node import Node
from waflib.Task import Task, RUN_ME
from waflib.Build import BuildContext

from scripts.utils import validate_result
from scripts.analyzer import AnalyzerServer

class RunTestTask(Task):
    color = 'PINK'
    vars = ['input_file', 'reference_file']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.force = args[0]
        self.executable = args[1]

    def runnable_status(self):
        if self.force:
            return RUN_ME
        return super().runnable_status()

    def run(self):
        Logs.pprint('CYAN', "Creating environment...")
        result = self.exec_command('cp %s %s' %
                                   (self.env.input_file, self.executable.parent.make_node('input_data.txt').abspath()))
        if result != 0: return result

        Logs.pprint('CYAN', "Working...")
        original_dir = os.getcwd()
        os.chdir(self.executable.parent.abspath())
        result = self.exec_command('%s input_data.txt output_data.txt' % self.executable.abspath())
        os.chdir(original_dir)         
        if result != 0: return result

        if self.env.reference_file:
            Logs.pprint('CYAN', "Reference checking...")
            try:
                validate_result(self.env.reference_file, self.executable.parent.find_node('output_data.txt').abspath())
                Logs.pprint('CYAN', "Everything is ok")
            except Exception as e:
                Logs.pprint('CYAN', "Error: %s" % str(e))
                return 1

        return 0

class CollectResultTask(Task):
    color = 'PINK'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container = args[0]
        self.bldnode = args[1]

    def runnable_status(self):
        return RUN_ME

    def run(self):
        Logs.pprint('CYAN', "Collect data...")
        current = {}

        with open(self.bldnode.find_node('current_profile.txt').abspath()) as profile:
            if (not next(profile).startswith("// Verbose: 1")):
                Logs.pprint('CYAN', "Incorrect profile format")
                return 1
            next(profile)
            
            for line in profile:
                line = line.split(' ')
                current[line[0]] = int(line[1])

        self.container.append(current)
        return 0

class PrintCollectedResultsTask(Task):
    color = 'PINK'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container = args[0]
        self.bldnode = args[1]

    def runnable_status(self):
        return RUN_ME

    def run(self):
        Logs.pprint('CYAN', "Process data...")
        keys = self.container[0].keys()
        count = len(self.container)
        
        total = {}
        detailed = {}

        for key in keys:
            total[key] = 0
            detailed[key] = []
            
        for test in self.container:
            for key in keys:
                total[key] += test[key]
                detailed[key].append(test[key])

        with open(self.bldnode.make_node('current_profile.txt').abspath(), 'w') as profile:
            profile.write("// Verbose: 1\n")
            profile.write("{0}\n".format(len(self.container[0])))
            for key in keys:
                profile.write("{0} {1}\n".format(key, total[key] / count))

        with open(self.bldnode.make_node('current_profile_detailed.json').abspath(), 'w') as profile:
                  json.dump(detailed, profile)

        return 0

class RunContext(BuildContext):
    cmd = 'debug'
    fun = 'debug'

    def run(self, force, executable):
        self.add_to_group(RunTestTask(force, self.bldnode.find_node(executable), env=self.env))

class RunTestsContext(BuildContext):
    cmd = 'run_tests'
    fun = 'run_tests'

    def run(self, aggregate, available_params, configurations):
        test_build_path = self.path.make_node(self.bldnode.name + '_tests')
       
        Options.lockfile = Options.lockfile + '_tests'
        Options.options.out = test_build_path.abspath()
        Options.options.profiling = self.env.profiling
        Options.options.input_file = os.path.relpath(self.env.input_file, self.path.abspath())
        Options.options.reference_file = os.path.relpath(self.env.reference_file, self.path.abspath())

        for configuration in configurations:
            for configuration_param in available_params:
                setattr(Options.options, configuration_param, configuration_param in configuration['modules'])

            Logs.pprint('PINK', 'Testing %s build...' % configuration['id'])
      
            Scripting.run_command('configure')
            Scripting.run_command('build')
            Scripting.run_command('perf' if aggregate else 'debug')

            self.exec_command('cp %s %s' % (
                test_build_path.find_node('current_profile.txt').abspath(),
                self.bldnode.make_node('%s_profile.txt' % configuration['id']).abspath()))

            if aggregate:
                self.exec_command('cp %s %s' % (
                    test_build_path.find_node('current_profile_detailed.json').abspath(),
                    self.bldnode.make_node('%s_profile_detailed.json' % configuration['id']).abspath()))
         

        Scripting.run_command('distclean')

class AnalyzeContext(BuildContext):
    cmd = 'analyze'
    fun = 'analyze'

    def run(self, port, result_path):
        AnalyzerServer(port, result_path).run()

class PerfContext(BuildContext):
    cmd = 'perf'
    fun = 'perf'

    def run(self, passes, executable):
        if self.env.profiling and self.env.profiling >= 2:
            ctx.fatal('Perf command is allowed only with profiling level 1 and 2')

        container = []

        for i in range(passes):
            self.add_to_group(RunTestTask(True, self.bldnode.find_node(executable), env=self.env))
            self.add_group()
            self.add_to_group(CollectResultTask(container, self.bldnode, env=self.env))
            self.add_group()

        self.add_to_group(PrintCollectedResultsTask(container, self.bldnode, env=self.env))
        
        
