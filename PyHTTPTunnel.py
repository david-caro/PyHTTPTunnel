#!/usr/bin/env python
#codung: utf-8
#Author: David Caro <david.caro.estevez@member.fsf.org
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import threading 
import sys, string, time
import socket, ssl
import argparse
import ConfigParser, os
import re

__version__ = '0.1'
## The best choice usually is a power of 2 2^12 should be ok
BUFLEN = 4096
CONFFILE = 'pytunnel.conf'
DEBUG = False
DEFAULT_OPTIONS = {'max_threads': '100',
                    'main_logfile': 'tunnel-main-sample.log',
                    'threads_logfile': 'tunnel-threads-sample.log',
                    'local_port': '8888',
                    'local_proto': 'http',
                    'local_cert': 'server.crt',
                    'local_key': 'server.key',
                    'remote_port': '8080',
                    'remote_host': 'localhost',
                    'remote_proto': 'http',
                    'remote_cert': 'server.crt',
                    'remote_key': 'server.key',
                    'request_regexps': '',
                    'response_regexps': '',
                    'request_extra_headers': 'X-Tunneled-From: %(local_proto)://%(local_ip):%(local_port)',
                    'response_extra_headers': 'X-Tunneled-To: %(remote_proto)://%(remote_host):%(remote_port)'
                  }

def csv2list( string ):
        parsed = [header.strip()
                for header 
                in string.split(',')]
        if parsed  == [('',)]: parsed = []
        return parsed


def log(message, fd=None, level='INFO'):
    if DEBUG or level=='CRIT': 
        if fd: 
            fd.write(':%s::::%s\n'%(threading.currentThread().getName(),message))
            fd.flush()
        print ':%s::::%s'%(threading.currentThread().getName(),message)
        sys.stdout.flush()

class ConnectionHandler:
    def __init__(self, connection, config, section):
        self.config = config
        self.section = section
        self.local_proto = config.get(section, 'local_proto')
        self.client = connection
        self.remote_host = config.get(section, 'remote_host')
        self.remote_port = config.getint(section, 'remote_port')
        self.remote_proto = config.get(section, 'remote_proto')
        self.remote_cert = config.get(section, 'remote_cert')
        self.remote_key = config.get(section, 'remote_key')
        self.target = None
        self.logfile = open(config.get(section, 'threads_logfile'),'a')
        self.with_headers = True

        try:
            self.target = self.connect_to_target()
            if not self.target: 
                if DEBUG: 
                    print "Can't connect to %s:%s."%(remote_host,remote_port)
                return
            log('connected to %s:%s.'%(self.remote_host,self.remote_port), self.logfile)
            log('fetching request...',self.logfile)
            request = self.get_request()
            log('got request',self.logfile)
            if not request: return 
            self.target.sendall('%s'%request)
            log('Sent request',self.logfile)
            response = self.get_response()
            log('Got reponse',self.logfile)
            self.client.sendall('%s'%response)
            log('Sent reponse',self.logfile)
        finally:
            if self.target: 
                log('Shutdowning socket target',self.logfile)
                self.target.shutdown(socket.SHUT_RDWR)
                log('Closing socket target',self.logfile)
                self.target.close()
            log('Shutdowning socket client',self.logfile)
            self.client.shutdown(socket.SHUT_RDWR)
            log('Closing socket client',self.logfile)
            self.client.close()
            log('Sockets closed',self.logfile)


    def get_request(self):
        log('get_request',self.logfile)
        self.client.settimeout(60.0)
        method, data=self.get_request_method()
        headers, data=self.get_headers(conn=self.client,old_data=data)
        if method == 'POST':
            content_length=self.get_content_length(headers)
            data=self.get_data(conn=self.client,length=content_length,old_data=data)
        elif not method == 'GET':
            log("::::::::: ERROR ::: Method %s not supported yet."%method,self.logfile)
            return False
        #log('::::::::: REQUEST FROM CLIENT %s:%s'%self.client.getpeername()+' ::::\n%s\n::::::::::'%(headers+'\r\n\r\n'+data),self.logfile)
        log('::::::::: REQUEST FROM CLIENT %s:%s'%self.client.getpeername()
                +' ::::\n%s\n%d\n::::::::::'%(headers,len(data)),
                self.logfile, 'CRIT')
        self.config.set(self.section, 'clientip', self.client.getpeername()[0])
        self.config.set(self.section, 'clientport','%s'%self.client.getpeername()[1])
        # parse the data and make the substitutions
        if data: 
            
            fixed_data=self.parse(data, 
                        [ list(pair.split(':')) 
                            for pair 
                            in csv2list(self.config.get(self.section, 'request_regexps'))]
                       )
        else: 
            fixed_data=data
        # fix the content lenght if necessary and set the HTTP version to 1.0 (chunks not supported yet)
        version_fixed_headers=self.fix_http_version(headers)
        if version_fixed_headers == False:
            log('::::::::: MALFORMED REQUEST MISSING HTTP VERSION HEADER :::::::::',self.logfile)
            self.with_headers=False
            fixed_headers=headers
        else:
            fixed_headers=version_fixed_headers
            fixed_headers=self.fix_content_length(fixed_headers,len(fixed_data))
            fixed_headers=fixed_headers \
                            +'\r\n'+'\r\n'.join(
                                           csv2list(self.config.get(self.section, 'request_extra_headers')))
        # assemble the request
        fixed_request=fixed_headers+'\r\n\r\n'+fixed_data
        #log('::::::::: REQUEST TO TARGET %s:%s'%self.target.getpeername()+' ::::\n%s\n::::::::::'%(fixed_request),self.logfile)
        log('::::::::: REQUEST TO TARGET %s:%s'%self.target.getpeername()+' ::::\n%s\n%d\n::::::::::'%(fixed_headers,len(fixed_data)),self.logfile)
        return fixed_request


    def get_response(self):
        log('get_response', self.logfile)
        headers, data = self.get_headers(conn=self.target, old_data='')
        log("Got response headers", self.logfile)
        log(headers,self.logfile)
        content_length = self.get_content_length(headers)
        if not content_length or content_length=='chunked':
            data = self.get_data(conn=self.target,
                                 length=content_length,
                                 old_data=data)
        elif len(data) < content_length:
            data = self.get_data(conn=self.target,
                                 length=content_length,
                                 old_data=data)
        #log('::::::::: RESPONSE FROM TARGET  %s:%s'%self.target.getpeername()+'::::\n%s\n::::::::::'%(headers+'\r\n\r\n'+data),self.logfile)
        log('::::::::: RESPONSE FROM TARGET  %s:%s' % self.target.getpeername()
            +'::::\n%s\n%d\n::::::::::' % (headers, len(data)), self.logfile)
        # parse the data and make the substitutions
        if data: 
            fixed_data = self.parse(data, 
                                    [ list(pair.split(':'))
                                      for pair
                                      in csv2list(self.config.get(self.section, 'response_regexps'))]
                        )
        else: 
            fixed_data = data
        # fix the content lenght if necessary and add the aditional haeders
        fixed_headers = ''
        if self.with_headers:
            # fix the content lenght if necessary and add the aditional haeders
            if headers:
                fixed_headers=self.fix_content_length(headers,len(fixed_data))
            else:
                fixed_headers=headers
            fixed_headers=self.fix_http_version(fixed_headers)
            if fixed_headers == False:
                log('::::::::: MALFORMED RESPONSE MISSING HTTP VERSION HEADER :::::::::',self.logfile)
                return False
            fixed_headers=fixed_headers \
                            +'\r\n'+'\r\n'.join(
                                        csv2list(self.config.get(self.section, 'response_extra_headers')))
        # assemble the response
        fixed_response=fixed_headers+'\r\n\r\n'+fixed_data
        #log('::::::::: RESPONSE TO CLIENT %s:%s'%self.client.getpeername()+'::::\n%s\n::::::::::'%(fixed_response),self.logfile)
        log('::::::::: RESPONSE TO CLIENT %s:%s'%self.client.getpeername()
            +'::::\n%s\n%d\n::::::::::'%(fixed_headers,len(fixed_data)),
            self.logfile)
        return fixed_response

    def fix_content_length(self,headers,new_length):
        log('fix_content_length',self.logfile)
        pattern=r'Content-Length: \d+'
        return re.sub(pattern, 'Content-Length: %d'%new_length, headers)

    def fix_http_version(self,headers):
        log('fix_http_version',self.logfile)
        pattern=r'HTTP/[\d].[\d]*'
        result=re.search(pattern, headers)
        if result:
            return re.sub(pattern, 'HTTP/1.0', headers)
        else:
            return False

    def parse(self, data, regexps):
        log('parse',self.logfile)
        fixeddata=data
        for regexp, substitute in regexps:
            fixeddata = re.sub(regexp, substitute, fixeddata)
        return fixeddata

              
    def get_request_method(self):
        log('get_request_method',self.logfile)
        method=''
        data = self.client.recv(BUFLEN)
        while 1:
            if ' ' in data:
                method = data.split(' ',1)[0]
            elif '\n' in data:
                method = data.split('\n',1)[0]
            if not method:
                newdata = self.client.recv(BUFLEN)
            if method or not newdata:
                break
            data += newdata
        log("Got method %s"%method)
        return method, data

    def get_content_length(self, headers):
        log('get_content_length',self.logfile)
        result_length=re.search('Content-Length: (?P<content_length>\d+)',headers)
        if result_length:
            content_length=int(result_length.group('content_length'))
        else:
            result_close=re.search('Connection: (?P<close>close)',headers)
            if result_close:
                content_length='close'
            else:
                result_type=re.search('Transfer-Encoding: (?P<encoding>chunked)',headers)
                if result_type:
                    content_length='chunked'
                else:
                    content_length=None
        log("Got content-length: %s"%content_length,self.logfile)
        return content_length

    def print_oct(self, string):
        log(string,self.logfile)
        log(''.join('-%s'%ord(char) for char in string))

    def get_headers(self,conn,old_data,extra_headers=''):
        log('get_headers',self.logfile)
        headers=old_data
        newdata=''
        method=''
        # check for different request endings
        endings = ('\r\n\r\n', '\n\n')
        while 1:
            for ending in endings:
                end = headers.find(ending)
                if end >= 0: break
            if end == -1:
                log("no suitable ending found")
                end = headers.find('\n')
                if end >= 0 and not self.fix_http_version(headers):
                    log("no HTTP version found")
                    ending='\n'
                else:
                    end = -1
            log('end=%d'%end, self.logfile)
            self.print_oct(headers)
            if end >= 0 : break
            time.sleep(0.1)
            newdata = conn.recv(BUFLEN)
            headers += newdata
        return headers[:end],headers[end+len(ending):]

    def get_chunk(self,conn,data):
    ## TODO
        log('get_chunk',self.logfile)
        end=data.find('\r\n')
        while end == -1:
            data+=conn.recv(BUFLEN)
            end=data.find('\r\n')
        headers=data[:end]
        length=int(headers, 16)
        log("Got chunk of %d bytes:"%length,self.logfile)
        if length==0:
            return headers, False
        body=data[end+2]
        while len(body)<length+2:
            body+=conn.recv(length+2-len(body))
        log("%d"%len(body[:length]),self.logfile)
        return headers+'\r\n'+body[:length],body[length+2:] 

    def get_data(self,conn,length=None,old_data=''):
        log('get_data',self.logfile)
        data=old_data
        if length=='chunked':
        # this means that the server will use http1.1 chunk protocol to send the response
            log('get_data::length=chunked',self.logfile)
            chunk, next_data=self.get_chunk(conn,data)
            data=chunk
            while next_data != False: 
                chunk, next_data=self.get_chunk(conn,next_data)
                data+=chunk
        elif length=='close':
        # this means that the server will close the connection, so we have to read everything we can.
            log('get_data::length=close',self.logfile)
            while 1:
                newdata=conn.recv(BUFLEN)
                data=data+newdata
                if not newdata: break
        elif length==None:
        # This means that the server did not send a Content-Length header and did not 
        # specify content-transer chunked nor connection: close, usually a malformed response.
            log('get_data::length=None',self.logfile)
            while 1:
                newdata=conn.recv(BUFLEN)
                data=data+newdata
                if len(newdata)<BUFLEN: break
        else:
        # The server sent a Content-Length header so we read the specified amount od words.
            log('get_data::length=%s'%length,self.logfile)
            while len(data)<length:
                data+=conn.recv(length-len(data))
        return data

    def connect_to_target(self):
        log('connect_to_target',self.logfile)
        (soc_family, _, _, _, address) = socket.getaddrinfo(self.remote_host, self.remote_port)[0]
        target = socket.socket(soc_family)
        target.settimeout(60.0)
        if self.remote_proto == 'https':
            try:
                target = ssl.wrap_socket(target)
            except Exception, e:
                log("::::::::: ERROR :::: Exception encountered attending remote %s:%d.\n%s"%(self.remote_host, self.remote_port, e),self.logfile)
                sys.stdout.flush()
                target.shutdown(socket.SHUT_RDWR)
                target.close()
                return None
        try:
            target.connect(address)
        except Exception, e:
            log("::::::::: ERROR :::: Exception encountered conencting to remote host %s:%d.\n%s"%(self.remote_host, self.remote_port, e),self.logfile)
            return None
        return target



class Tunnel:
    def __init__(self, config, section):
        self.config = config
        self.section = section
        self.max_threads = config.get(section, 'max_threads')
        self.main_logfile = config.get(section, 'main_logfile')
        self.local_port = config.getint(section, 'local_port')
        self.local_ip = config.get(section, 'local_ip')
        self.local_proto = config.get(section, 'local_proto')
        self.local_cert = config.get(section, 'local_cert')
        self.local_key = config.get(section, 'local_key')
        self.remote_port = int(config.get(section, 'remote_port'))
        self.remote_host = config.get(section, 'remote_host')
        self.remote_proto = config.get(section, 'remote_proto')
        sys.stdout.flush()
        self.IPv6 = 'false'
        self.timeout = 60
        self.sock = None
        self.logfile = open(self.main_logfile,'a')
        self.threads = []
        log("Starting thread server at %s://%s:%s --> %s://%s:%s"%(
                self.local_proto, self.local_ip, self.local_port, 
                self.remote_proto, self.remote_host, self.remote_port))
        self.run()

    def run(self,handler=ConnectionHandler):
        if self.IPv6==True:
            sock_type=socket.AF_INET6
        else:
            sock_type=socket.AF_INET
        
        try:
            self.sock = socket.socket(sock_type)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.local_ip, self.local_port))
            log("Serving on %s:%d."%(self.local_ip, self.local_port),self.logfile)
            sys.stdout.flush()
            self.sock.listen(5)
            while 1:
                try:
                    count=0
                    while threading.activeCount() > self.max_threads:
                        count=count+1
                        time.sleep(0.1)
                        if count==self.max_threads:
                            log("Max threads %d reached... waiting for someone to end..."%self.max_threads,self.logfile)
                            count=0
                    newconn, addr=self.sock.accept()
                    log('Connected from %s:%d'%addr,self.logfile)
                    if self.local_proto == 'https':
                        try:
                            conn = ssl.wrap_socket(newconn, 
                                                   certfile=self.local_cert, 
                                                   keyfile=self.local_key, 
                                                   server_side=True)
                        except Exception, e:
                            log("Error while trying to wrap the ssl connection with %s:%d:\n%s"%(addr[0], addr[1],e),self.logfile)
                            sys.stdout.flush()
                            print "closing"
                            newconn.send('ERROR:wrong proto!')
                            newconn.shutdown(socket.SHUT_RDWR)
                            newconn.close()
                            print "closed"
                            continue
                    else:
                        conn=newconn
                    log('Threads running:%d'%threading.activeCount(),
                        self.logfile)
                    newthread=threading.Thread(target=handler, 
                                               args=(conn, self.config, self.section))
                    newthread.start()
                    #self.threads.append(newthread)
                except KeyboardInterrupt:
                    break
                except Exception, e:
                    log("ERROR on main loop",self.logfile)
                    log('%s'%e,self.logfile)
                    print e
        finally:
            self.stop()
    
    def stop(self):
        log("waiting for threads to end",self.logfile)
        log("Threads still alive:\n\t",self.logfile)
        for thread in threading.enumerate():
            print type(thread)
            print thread
            log("\tThread %s"%thread.getName(),self.logfile)
        #for thread in self.threads:
        #    thread.join()
        log("Stopping..",self.logfile)
        sys.stdout.flush()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
        except:
            pass
        self.logfile.close()


def parse_config(conf_file):
    config = ConfigParser.SafeConfigParser(DEFAULT_OPTIONS)
    config.read(conf_file)
    for section in config.sections():
        ### todo, launch a thread for each section, not only the first one.
        print "Starting tunnel '%s'\n\t%s://%s:%s --> %s://%s:%s"\
                %(section, config.get(section, 'local_proto'),
                    config.get(section, 'local_ip'),
                    config.get(section, 'local_port'),
                    config.get(section, 'remote_proto'),
                    config.get(section, 'remote_host'),
                    config.get(section, 'remote_port'))
        sys.stdout.flush()
        server=Tunnel(config, section)
        return server

def create_sample_config(conf_file):
    config = ConfigParser.RawConfigParser()
    config.add_section('Sample')
    for option, value in DEFAULT_OPTIONS.items():
        config.set('Sample', option, value)
    configfile=open(conf_file, 'wb')
    try:
        config.write(configfile)
    finally:
        configfile.close()
    
        
     
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
            description='Simple and agile transparent HTTP/HTTPS Proxy')
    parser.add_argument('--local_ip', metavar='local_ip', default='0.0.0.0', 
            help='Source ip to listen to')
    parser.add_argument('--local_port', metavar='local_port', type=int, 
            default=8888, help='Source port to listen to')
    parser.add_argument('--remote_host', metavar='remote_host', 
            default='127.0.0.1', help='Host to connect to')
    parser.add_argument('--remote_port', metavar='remote_port', type=int, 
            default=8080, help='Port to connect to')
    parser.add_argument('--config', metavar='conf_file', 
            help='Configuration file, overrides all the other options')
    parser.add_argument('--debug', default=False, action='store_true', 
            help='Verbose mode, dump all the requests and responses.')
    parser.add_argument('--max_threads', default=100, type=int, 
            help='Max number of simultaneous threads to launch (100 by default).')
    parser.add_argument('--create_config', action='store_true', 
            default=False, help='Create a sample config file')

    args = parser.parse_args()
    
    if args.create_config:
        if not os.path.isfile(CONFFILE):
            print "Sample config file created at %s"%CONFFILE
            create_sample_config(CONFFILE)
        else:
            print "Config file %s already exists."%CONFFILE
        sys.exit(0)

    DEBUG = args.debug

    try:
        if args.config:
            if os.path.isfile(args.config):
                parse_config(args.config)
            else:
                print "Config file %s not found..."%args.config
                sys.exit(0)
        else:
                conf_opts={ 'local_ip': args.local_ip,
                            'local_port': args.local_port,
                            'remote_host': args.remote_host,
                            'remote_port': args.remote_port}
                config = ConfigParser.SafeConfigParser(DEFAULT_OPTIONS)
                config.add_section('custom')
                server = Tunnel(config, 'custom')
    except KeyboardInterrupt:
        print "Exiting."


