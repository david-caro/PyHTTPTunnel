#!/usr/bin/env python
import multiprocessing as mp
import os



class Worker:
    def __init__(self, queue):
        self.queue=queue
    
    def run(self):
        while 1:
            job=self.queue.get()
            print job

def f(queue):
    print 'module name:', __name__
    print 'parent process:', os.getppid()
    print 'process id:', os.getpid()
    print "worker up!"
    while 1:
            job=queue.get()
            print os.getpid(), '     got job'
            print job
        

class Main:
    def __init__(self):
        print "main"
        self.queue=mp.Queue()
        self.workers=[]
        for i in range(mp.cpu_count()):
            print 'starting worker %d'%i
            self.workers.append(mp.Process(target=f,args=(self.queue,)))
        
    def start(self):
        for worker in self.workers:
            worker.start()
    
    def add_job(self, job):
        self.queue.put(job)

    def exit(self):
        print "Stopping processes..."
        for worker in self.workers:
            worker.stop()
            worker.join()
        print "Bye"

if __name__=='__main__':
    print mp.cpu_count()
