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

#import thread, threading
import multiprocessing as mp
import sys, string
import socket, ssl
import argparse
import ConfigParser, os
import re

__version__ = '0.1'
## The best choice usually is a power of 2 2^12 should be ok
BUFLEN = 4096
CONFFILE = 'pytunnel.conf'
DEBUG = False

CRIT=0
WARN=1
INFO=2

def log(message, prio=INFO):
    if DEBUG:
        print message
        sys.stdout.flush()
    elif prio == 0:
        print message
        sys.stdout.flush()

def process(self,
            remote_host, remote_port, 
            local_proto='http', remote_proto='http',
            remote_cert='server.crt', remote_key='server.key',
            request_regexps=None, response_regexps=None,
            request_extra_headers=None, response_extra_headers=None,
            max_requests='4', queue=None):
    request_extra_headers=request_extra_headers or []
    response_extra_headers=response_extra_headers or []
    request_regexps=request_regexps or []
    response_regexps=response_regexps or []
    requests=0
    while requests < max_requests and exit_flag == 0:
        client=queue.get()
        try:
            target = connect_to_target(remote_host, remote_port, remote_proto)
            if not target: 
                log("Can't connect to %s:%s."%(remote_host,remote_port))
                return
            request = get_request()
            if not request: return 
            target.sendall('%s'%request)
            response=get_response()
            client.sendall('%s'%response)
        finally:
            if target: target.close()
            if local_proto=='https':
               if client: client.shutdown(socket.SHUT_RDWR)
            client.close()
            queue.task_done()
    

def get_request(client,  ):
    method, data=get_request_method(client)
    headers, data=get_headers(conn=client,old_data=data)
    if method == 'POST':
        content_length=get_content_length(headers)
        data=get_data(conn=client,length=content_length,old_data=data)
    elif not method == 'GET':
        log("::::::::: ERROR ::: Method %s not supported yet."%method)
        return False
    #log('::::::::: REQUEST FROM CLIENT %s:%s'%client.getpeername()+' ::::\n%s\n::::::::::'%(headers+'\r\n\r\n'+data)
    log('::::::::: REQUEST FROM CLIENT %s:%s'%client.getpeername()+' ::::\n%s\n%d\n::::::::::'%(headers,len(data))
    # parse the data and make the substitutions
    if data: fixed_data=parse_data(data,request_regexps)
    else: fixed_data=data
    # fix the content lenght if necessary and set the HTTP version to 1.0 (chunks not supported yet)
    fixed_headers=fix_content_length(headers,len(fixed_data))
    fixed_headers=fix_http_version(fixed_headers)
    fixed_headers=fixed_headers+'\r\n'+'\r\n'.join(request_extra_headers)
    # assemble the request
    fixed_request=fixed_headers+'\r\n\r\n'+fixed_data
    #log('::::::::: REQUEST TO TARGET %s:%s'%target.getpeername()+' ::::\n%s\n::::::::::'%(fixed_request))
    log('::::::::: REQUEST TO TARGET %s:%s'%target.getpeername()+' ::::\n%s\n%d\n::::::::::'%(fixed_headers,len(fixed_data)))
    return fixed_request


def get_response(self):
    headers, data=get_headers(conn=target,old_data='')
    log("Got response headers")
    log(headers)
    content_length=get_content_length(headers)
    if not content_length or content_length=='chunked':
        data=get_data(conn=target,length=content_length,old_data=data)
    elif len(data)<content_length:
        data=get_data(conn=target,length=content_length,old_data=data)
    #log('::::::::: RESPONSE FROM TARGET  %s:%s'%target.getpeername()+'::::\n%s\n::::::::::'%(headers+'\r\n\r\n'+data))
    log('::::::::: RESPONSE FROM TARGET  %s:%s'%target.getpeername()+'::::\n%s\n%d\n::::::::::'%(headers,len(data)))
    # parse the data and make the substitutions
    if data: fixed_data=parse_data(data,response_regexps)
    else: fixed_data=data
    # fix the content lenght if necessary and add the aditional haeders
    if headers:
        fixed_headers=fix_content_length(headers,len(fixed_data))
    else:
        fixed_headers=headers
    fixed_headers=fixed_headers+'\r\n'+'\r\n'.join(response_extra_headers)
    # assemble the response
    fixed_response=fixed_headers+'\r\n\r\n'+fixed_data
    #log('::::::::: RESPONSE TO CLIENT %s:%s'%client.getpeername()+'::::\n%s\n::::::::::'%(fixed_response))
    log('::::::::: RESPONSE TO CLIENT %s:%s'%client.getpeername()+'::::\n%s\n%d\n::::::::::'%(fixed_headers,len(fixed_data)))
    return fixed_response

def fix_content_length(self,headers,new_length):
    pattern=r'Content-Length: \d+'
    return re.sub(pattern, 'Content-Length: %d'%new_length, headers)

def fix_http_version(self,headers):
    pattern=r'HTTP/1.1'
    return re.sub(pattern, 'HTTP/1.0', headers)

def parse_data(self, data, regexps):
    fixeddata=data
    for regexp, substitute in regexps:
        fixeddata = fixeddata.replace(regexp, substitute)
    return fixeddata
          
def get_request_method(client):
    method=''
    data = client.recv(BUFLEN)
    if method=='':
        method=data.split(' ',1)[0]
    return method, data

def get_content_length(self, headers):
    result_length=re.search('Content-Length: (?P<content_length>\d+)',headers)
    if result_length:
        content_length=int(result_length.group('content_length'))
    else:
        result_type=re.search('Transfer-Encoding: (?P<encoding>chunked)',headers)
        if result_type:
            content_length='chunked'
        else:
            result_close=re.search('Connection: (?P<close>close)',headers)
            if result_close:
                content_length='close'
            else:
                content_length=None
    print "Got content-length:", content_length
    return content_length

def get_headers(conn,old_data,extra_headers=''):
    headers=old_data
    newdata=''
    method=''
    end = headers.find('\r\n\r\n')
    if end != -1:
        return headers[:end],headers[end+4:]
    while 1:
        newdata = conn.recv(BUFLEN)
        headers += newdata
        end = headers.find('\r\n\r\n')
        if end != -1: break
    return headers[:end],headers[end+4:]

def get_chunk(self,conn,data):
## TODO
    end=data.find('\r\n')
    while end == -1:
        data+=conn.recv(BUFLEN)
        end=data.find('\r\n')
    headers=data[:end]
    print headers
    length=int(headers, 16)
    print "Got chunk of %d bytes:"%length
    if length==0:
        return headers, False
    body=data[end+2]
    while len(body)<length+2:
        body+=conn.recv(length+2-len(body))
    print "%d"%len(body[:length])
    return headers+'\r\n'+body[:length],body[length+2:] 

def get_data(self,conn,length=None,old_data=''):
    data=old_data
    if length=='chunked':
    # this means that the server will use http1.1 chunk protocol to send the response
        chunk, next_data=get_chunk(conn,data)
        data=chunk
        while next_data != False: 
            chunk, next_data=get_chunk(conn,next_data)
            data+=chunk
    elif length=='close':
    # this means that the server will close the connection, so we have to read everything we can.
        while 1:
            newdata=conn.recv(BUFLEN)
            data=data+newdata
            if not newdata: break
    elif length==None:
    # This means that the server did not send a Content-Length header and did not 
    # specify content-transer chunked nor connection: close, usually a malformed response.
        while 1:
            newdata=conn.recv(BUFLEN)
            data=data+newdata
            if len(newdata)<BUFLEN: break
    else:
    # The server sent a Content-Length header so we read the specified amount od words.
        while len(data)<length:
            data+=conn.recv(length-len(data))
    return data

def connect_to_target(remote_host, remote_port, remote_proto):
    (soc_family, _, _, _, address) = socket.getaddrinfo(remote_host, remote_port)[0]
    target = socket.socket(soc_family)
    if remote_proto == 'https':
        try:
            target = ssl.wrap_socket(target)
        except Exception:
            log("::::::::: ERROR :::: SSL protocol not supported by remote %s:%d."%(remote_host, remote_port),CRIT)
            return None
    target.connect(address)
    return target



class TunnelMaster:
    def __init__(self,
            max_threads=50, min_threads=1, requests_per_thread='1',
            local_port=8888, local_ip='127.0.0.1', local_proto='http', 
            remote_port=8080, remote_host='127.0.0.1', remote_proto='http',
            local_cert='server.crt', local_key='server.key',
            remote_cert='server.crt', remote_key='server.key',
            request_extra_headers='', response_extra_headers='',
            request_regexps=None, response_regexps=None,
            IPv6=False,timeout=60):
        log("Starting thread server at %s://%s:%s --> %s://%s:%s"%(local_proto, local_ip, local_port, remote_proto, remote_host, remote_port),CRIT)
        self.local_port=int(local_port)
        self.local_ip=local_ip
        self.local_proto=local_proto
        self.remote_port=int(remote_port)
        self.remote_host=remote_host
        self.remote_proto=remote_proto
        self.local_cert=local_cert
        self.local_key=local_key
        self.remote_cert=remote_cert
        self.remote_key=remote_key
        self.request_extra_headers=request_extra_headers
        self.response_extra_headers=response_extra_headers
        self.request_regexps=request_regexps or []
        self.response_regexps=response_regexps or []
        self.IPv6=IPv6
        self.timeout=timeout
        self.sock=None
        self.run()

    def run(self,handler=ConnectionHandler):
        import thread
        if self.IPv6==True:
            sock_type=socket.AF_INET6
        else:
            sock_type=socket.AF_INET
        
        try:
            self.sock = socket.socket(sock_type)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.local_ip, self.local_port))
            log("Serving on %s:%d."%(self.local_ip, self.local_port).CRIT)
            sys.stdout.flush()
            self.sock.listen(5)
            while 1:
                try:
                    self.wait_for_threads()
                    conn, addr=self.sock.accept()
                    if self.local_proto == 'https':
                        conn = ssl.wrap_socket(conn, certfile=self.local_cert, keyfile=self.local_key, server_side=True)
                    newthread=thread.start_new_thread(handler, 
                            (conn, addr, self.remote_host, self.remote_port,
                                    self.local_proto, self.remote_proto,
                                    self.remote_cert, self.remote_key,
                                    self.request_regexps, self.response_regexps,
                                    self.request_extra_headers, self.response_extra_headers))
                except Exception, e:
		            log(e,CRIT)
        finally:
            self.stop()

    def wait_for_threads(self):
        while
    
    def stop(self):
        log("Stopping..",CRIT)
        sys.stdout.flush()
        self.sock.close()


def parse_config(conf_file):
    config = ConfigParser.SafeConfigParser({'max_threads': '100', 
                                        'min_threads': '5', 
                                        'requests_per_thread': '4', 
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
                                        'response_regexps':'',
                                        'request_extra_headers': 'X-Tunneled-From: %(local_proto)://%(local_ip):%(local_port)',
                                        'response_extra_headers': 'X-Tunneled-To: %(remote_proto)://%(remote_host):%(remote_port)'})
    config.read(conf_file)
    for section in config.sections():
        ### todo, launch a thread for each section, not only the first one.
        max_threads=config.get(section, 'max_threads')
        min_threads=config.get(section, 'min_threads')
        requests_per_thread=config.get(section, 'requests_per_thread')
        local_port=config.get(section, 'local_port')
        local_ip=config.get(section, 'local_ip')
        local_proto=config.get(section, 'local_proto')
        local_cert=config.get(section, 'local_cert')
        local_key=config.get(section, 'local_key')
        remote_port=config.get(section, 'remote_port')
        remote_host=config.get(section, 'remote_host')
        remote_proto=config.get(section, 'remote_proto')
        remote_cert=config.get(section, 'remote_cert')
        remote_key=config.get(section, 'remote_key')
        request_extra_headers=[header.strip() for header in config.get(section, 'request_extra_headers').split(',')]
        response_extra_headers=[header.strip() for header in config.get(section, 'response_extra_headers').split(',')]
        request_regexps=[ tuple(pair.split(':')) for pair in config.get(section, 'request_regexps').split(',') ]
        if request_regexps == [('',)]: request_regexps=[]
        response_regexps=[ tuple(pair.split(':')) for pair in config.get(section, 'response_regexps').split(',') ]
        if response_regexps == [('',)]: response_regexps=[]
        log("Starting tunnel '%s'\n\t%s://%s:%s --> %s://%s:%s",CRIT)
                %(section,local_proto,local_ip,local_port,remote_proto,remote_host,remote_port)

        server=Tunnel(max_threads=max_threads,min_threads=min_threads,requests_per_thread=requests_per_thread,
                local_port=local_port, local_ip=local_ip, local_proto=local_proto,

                remote_port=remote_port, remote_host=remote_host, remote_proto=remote_proto,
                remote_cert=remote_cert, remote_key=remote_key,
                request_extra_headers=request_extra_headers, response_extra_headers=response_extra_headers,
                request_regexps=request_regexps, response_regexps=response_regexps)
        return server

def create_sample_config(conf_file):
    config = ConfigParser.RawConfigParser()
    config.add_section('Sample')
    config.add_section('DEFAULT')
    config.set('DEFAULT', 'max_threads', '100')
    config.set('DEFAULT', 'min_threads', '5')
    config.set('DEFAULT', 'requests_per_thread', '4')
    config.set('Sample', 'logfile', 'tunnel-sample.log')
    config.set('Sample', 'local_port', '8080')
    config.set('Sample', 'local_ip', '127.0.0.1')
    config.set('Sample', 'local_proto', 'http')
    config.set('Sample', 'local_cert', 'server.crt')
    config.set('Sample', 'local_key', 'server.key')
    config.set('Sample', 'remote_host', 'localhost')
    config.set('Sample', 'remote_port', '80')
    config.set('Sample', 'remote_proto', 'http')
    config.set('Sample', 'remote_cert', '%(local_cert)s')
    config.set('Sample', 'remote_key', '$(local_key)s')
    config.set('Sample', 'request_extra_headers', 'X-Tunneled-From: %(local_proto)s://%(local_ip)s:%(local_port)s')
    config.set('Sample', 'response_extra_headers', 'X-Tunneled-To: %(remote_proto)s://%(remote_host)s:%(remote_port)s')
    config.set('Sample', 'request_regexps', 'regexp1:subst1,regexp2:subst2')
    config.set('Sample', 'response_regexps', 'regexp1:subst1,regexp2:subst2')
    configfile=open(conf_file, 'wb')
    try:
        config.write(configfile)
    finally:
        configfile.close()
    
        
     
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Simple and agile transparent HTTP/HTTPS Proxy')
    parser.add_argument('--local_ip', metavar='local_ip', default='0.0.0.0', help='Source ip to listen to')
    parser.add_argument('--local_port', metavar='local_port', type=int, default=8888, help='Source port to listen to')
    parser.add_argument('--remote_host', metavar='remote_host', default='127.0.0.1', help='Host to connect to')
    parser.add_argument('--remote_port', metavar='remote_port', type=int, default=8080, help='Port to connect to')
    parser.add_argument('--config', metavar='conf_file', help='Configuration file, overrides all the other options')
    parser.add_argument('--debug', default=False, action='store_true', help='Verbose mode, dump all the requests and responses.')
    parser.add_argument('--create_config', action='store_true', default=False, help='Create a sample config file')

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
                local_ip=args.local_ip
                local_port=args.local_port
                remote_host=args.remote_host
                remote_port=args.remote_port
                server=Tunnel(local_ip=local_ip,local_port=local_port,remote_host=remote_host,remote_port=remote_port)
    except KeyboardInterrupt:
        print "Exiting."


