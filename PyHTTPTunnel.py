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

import thread, threading, 
import sys
import socket, ssl
import argparse
import ConfigParser, os

__version__ = '0.1'
BUFLEN = 1024
CONFFILE = 'pytunnel.conf'
CERTFILE = 'server.crt'
KEYFILE = 'server.key'

class ConnectionHandler:
    def __init__(self, connection, address, timeout, 
                    remote_host, remote_port, 
                    local_proto='http', remote_proto='http'):
        self.client = connection
        self.timeout = timeout
        self.remote_host=remote_host
        self.remote_port=remote_port
        self.remote_proto=remote_proto
        self.target=None

        try:
            self.request = self.get_request()
            if not self.request:
                if local_proto=='https':
                    self.client.shutdown(socket.SHUT_RDWR)
                self.client.close()
                return False
            self.target = self.connect_to_target()
            self.forward_request()
            self.response=self.read_response()
            self.reply_to_client()
        finally:
            if self.target: self.target.close()
            if local_proto=='https':
               if self.client: self.client.shutdown(socket.SHUT_RDWR)
            if self.client: self.client.close()

    def get_request(self):
        method, data=self.get_request_method()
        request=data
        if method == 'GET':
            request, data=self.get_headers(old_data=request)
        elif method == 'POST':
            request, data=self.get_headers(old_data=request)
            content_length=self.get_content_length(request)
            print "OLDDATA::::\n%s\n:::::"%data
            data=self.get_POST_data(length=content_length,old_data=data)
            request=request+data
        else:
            print "ERROR ::: Method %s not supported yet."%method
            return False
        print 'REQUEST FROM CLIENT ::::\n%s\n::::::::::'%request
        return request
              
    def get_request_method(self):
        method=''
        data = self.client.recv(BUFLEN)
        if method=='':
            method=data.split(' ',1)[0]
        return method, data

    def get_content_length(self, headers):
        import re
        result=re.search('Content-Length: (?P<content_length>\d+)',headers)
        content_length=result.group('content_length')
        print 'content_length ::::\n%s\n::::::::::'%content_length
        return int(content_length)

    def get_headers(self,old_data):
        headers=old_data
        newdata=''
        method=''
        end = headers.find('\r\n\r\n')
        if end != -1:
            return headers[:end+4],headers[end+4:]
        while 1:
            newdata = self.client.recv(BUFLEN)
            for char in newdata:
                print ord(char)
            headers += newdata
            end = headers.find('\r\n\r\n')
            if end != -1:
                break
        print 'HEADERS ::::\n%s\n::::::::::'%headers[:end+2]
        return headers[:end+2],headers[end+2:]

    def get_POST_data(self,length,old_data):
        data=old_data
        while len(data)<length:
            newdata = self.client.recv(BUFLEN)
            data=data+newdata
        return data[:length]
    

    def connect_to_target(self):
        (soc_family, _, _, _, address) = socket.getaddrinfo(self.remote_host, self.remote_port)[0]
        target = socket.socket(soc_family)
        if self.remote_proto == 'https':
            target = ssl.wrap_socket(target)
        target.connect(address)
        return target

    def forward_request(self):
        print "REQUEST TO TARGET ::::::::::\n%s\n::::::::::::"%self.request
        self.target.send('%s'%self.request)

    def read_response(self):
        response=''
        while 1:
            data=self.target.recv(BUFLEN)
            if not data: break
            response+=data
        print "RESPONSE FROM TARGET ::::::\n%s\n:::::::::"%response
        return response
    
    def reply_to_client(self):
        print "RESPONSE TO CLIENT ::::::\n%s\n:::::::::"%self.response
        self.client.send("%s"%self.response)


class Tunnel(threading.Thread):
    def __init__(self,
            local_port=8080, local_ip='127.0.0.1', local_proto='http', 
            remote_port=80, remote_host='127.0.0.1', remote_proto='http',
            request_extra_headers='', response_extra_headers='',
            IPv6=False,timeout=60):
        print "Starting thread server at %s://%s:%s --> %s://%s:%s"%(local_proto, local_ip, local_port, remote_proto, remote_host, remote_port)
        threading.Thread.__init__(self)
        self.local_port=int(local_port)
        self.local_ip=local_ip
        self.local_proto=local_proto
        self.remote_port=int(remote_port)
        self.remote_host=remote_host
        self.remote_proto=remote_proto
        self.IPv6=IPv6
        self.timeout=timeout

    def run(self,handler=ConnectionHandler):
        import thread
        if self.IPv6==True:
            sock_type=socket.AF_INET6
        else:
            sock_type=socket.AF_INET
        
        ## Only python >=3.2
        #if self.local_proto == 'https':
        #    context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
        #    context.load_cert_chain(certfile=CERTFILE, keyfile=KEYFILE)

        sock = socket.socket(sock_type)
        sock.bind((self.local_ip, self.local_port))
        print "Serving on %s:%d."%(self.local_ip, self.local_port)
        sock.listen(5)
        while 1:
            conn, addr=sock.accept()
            if self.local_proto == 'https':
                conn = ssl.wrap_socket(conn, certfile=CERTFILE, keyfile=KEYFILE, server_side=True)
            thread.start_new_thread(handler, 
                    (conn, addr, self.timeout,self.remote_host,self.remote_port,
                            self.local_proto,self.remote_proto))
        sock.close()


def parse_config(conf_file):
    config = ConfigParser.SafeConfigParser({'local_port': '8080', 
                                        'local_proto': 'http',
                                        'remote_port': '80',
                                        'remote_host': 'localhost',
                                        'remote_proto': 'http',
                                        'request_extra_headers': 'X-Tunneled-From: %(local_proto)://%(local_ip):%(local_port)',
                                        'response_extra_headers': 'X-Tunneled-To: %(remote_proto)://%(remote_host):%(remote_port)'})
    threads=[]
    config.read(conf_file)
    for section in config.sections():
        local_port=config.get(section, 'local_port')
        local_ip=config.get(section, 'local_ip')
        local_proto=config.get(section, 'local_proto')
        remote_port=config.get(section, 'remote_port')
        remote_host=config.get(section, 'remote_host')
        remote_proto=config.get(section, 'remote_proto')
        request_extra_headers=config.get(section, 'request_extra_headers',1)
        response_extra_headers=config.get(section, 'response_extra_headers',1)
        print "Starting tunnel '%s'\n\t%s://%s:%s --> %s://%s:%s"\
                %(section,local_proto,local_ip,local_port,remote_proto,remote_host,remote_port)
        #start_server(local_port, local_ip, local_proto,remote_port, remote_host, remote_proto, request_extra_headers, response_extra_headers)
        newserver=Tunnel(local_port=local_port, local_ip=local_ip, local_proto=local_proto,
                remote_port=remote_port, remote_host=remote_host, remote_proto=remote_proto,
                request_extra_headers=request_extra_headers, response_extra_headers=response_extra_headers)
        threads.append(newserver)
    return threads

def create_sample_config(conf_file):
    config = ConfigParser.RawConfigParser()
    config.add_section('Sample')
    config.set('Sample', 'logfile', 'tunnel-sample.log')
    config.set('Sample', 'local_port', '8080')
    config.set('Sample', 'local_ip', '127.0.0.1')
    config.set('Sample', 'local_proto', 'http')
    config.set('Sample', 'remote_host', 'localhost')
    config.set('Sample', 'remote_port', '80')
    config.set('Sample', 'remote_proto', 'http')
    config.set('Sample', 'request_extra_headers', 'X-Tunneled-From: %(local_proto)://%(local_ip):%(local_port)')
    config.set('Sample', 'response_extra_headers', 'X-Tunneled-To: %(remote_proto)://%(remote_host):%(remote_port)')
    with open(conf_file, 'wb') as configfile:
        config.write(configfile)
        
     
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Simple and agile transparent HTTP/HTTPS Proxy')
    parser.add_argument('--local_port', metavar='local_port', type=int, default=8080, help='Source port to listen to')
    parser.add_argument('--remote_host', metavar='remote_host', default='127.0.0.1', help='Host to connect to')
    parser.add_argument('--remote_port', metavar='remote_port', type=int, default=80, help='Port to connect to')
    parser.add_argument('--config', metavar='conf_file', help='Configuration file, overrides all the other options')

    args = parser.parse_args()
    
    threads=[]

    if args.config:
        if os.path.isfile(args.config):
            threads=parse_config(args.config)
        else:
            print "Config file %s not found..."%args.config
            sys.exit(0)
    else:
        local_port=args.local_port
        remote_host=args.remote_host
        remote_port=args.remote_port
        if not os.path.isfile(CONFFILE):
            print "Sample config file created at %s"%CONFFILE
            create_sample_config(CONFFILE)
        server=Tunnel(local_port=local_port,remote_host=remote_host,remote_port=remote_port)
        threads.append(server)

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
        

