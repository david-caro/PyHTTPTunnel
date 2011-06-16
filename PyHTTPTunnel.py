#!/usr/bin/env python
#codung: utf-8
"""
Author: David Caro <david.caro.estevez@member.fsf.org

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

   This program is a simple HTTP/HTTPS proxy capable of  modifying the request 
   and response headers and the data persed on the reques an the response.
   Mainly is a little program I wrote to learn programming python.

"""

import os
import sys
import threading 
import re
import time
import socket
import ssl
import argparse
import ConfigParser

__version__ = '0.1'
## The best choice usually is a power of 2 2^12 should be ok
BUFLEN = 4096
CONFFILE = 'pytunnel.conf'
DEBUG = False

def log(message, logfile=None, level='INFO'):
    """
    Simple log function that appends the thread id to the message, only if the 
    debug option is enabled.

    """
    if DEBUG or level == 'CRIT': 
        if logfile: 
            logfile.write(':%s::::%s\n' % (threading.current_thread(), 
                                            message))
            logfile.flush()
        print ':%s::::%s' % (threading.current_thread(), message)
        sys.stdout.flush()


class ConnectionHandler:
    """
    This is the class that will hande the incomming connection, connect to the 
    target, parde the headers and the data.

    """

    def __init__(self, logfile, connection, 
                    remote_host, remote_port, 
                    local_proto='http', remote_proto='http',
                    remote_cert='server.crt', remote_key='server.key',
                    request_regexps=None, response_regexps=None,
                    request_extra_headers=None, response_extra_headers=None):
        self.local_proto = local_proto
        self.client = connection
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.remote_proto = remote_proto
        self.remote_cert = remote_cert
        self.remote_key = remote_key
        self.request_extra_headers = request_extra_headers or []
        self.response_extra_headers = response_extra_headers or []
        self.request_regexps = request_regexps or []
        self.response_regexps = response_regexps or []
        self.target = None
        self.logfile = open(logfile, 'a')

        print "THREAD DEBUG=",DEBUG
        sys.stdout.flush()

        try:
            self.target = self.connect_to_target()
            log('connected to %s:%s.' % (remote_host, remote_port), 
                    self.logfile)
            if not self.target: 
                log("Can't connect to %s:%s." % (remote_host, remote_port), 
                        self.logfile)
                return
            log('fetching request...', self.logfile)
            request = self.get_request()
            log('got request', self.logfile)
            if not request: 
                return 
            self.target.sendall('%s' % request)
            log('Sent request', self.logfile)
            response = self.get_response()
            log('Got reponse', self.logfile)
            self.client.sendall('%s' % response)
            log('Sent reponse', self.logfile)
        finally:
            if self.target: 
                log('Shutdowning socket target', self.logfile)
                self.target.shutdown(socket.SHUT_RDWR)
                log('Closing socket target', self.logfile)
                self.target.close()
            log('Shutdowning socket client', self.logfile)
            self.client.shutdown(socket.SHUT_RDWR)
            log('Closing socket client', self.logfile)
            self.client.close()
            log('Sockets closed', self.logfile)

    def get_request(self):
        """
        Get the request data and headers, parse it and return the modified 
        request.

        """
        log('get_request', self.logfile)
        self.client.settimeout(60.0)
        method, data = self.get_request_method()
        headers, data = self.get_headers(conn=self.client, old_data=data)
        if method == 'POST':
            content_length = self.get_content_length(headers)
            data = self.get_data(conn=self.client,
                    length=content_length, old_data=data)
        elif not method == 'GET':
            log("::::::::: ERROR ::: Method %s not supported yet." % method, 
                self.logfile)
            return False
        # log('::::::::: REQUEST FROM CLIENT %s:%s' % self.client.getpeername()
        # + ' ::::\n%s\n::::::::::' % (headers + '\r\n\r\n' + data))
        log('::::::::: REQUEST FROM CLIENT %s:%s' % self.client.getpeername() +
            ' ::::\n%s\n%d\n::::::::::' % (headers, len(data)), 
            self.logfile)
        # parse the data and make the substitutions
        if data: 
            fixed_data = self.parse_data(data, self.request_regexps)
        else: 
            fixed_data = data
        # fix the content lenght if necessary and set the HTTP version to 1.0 
        # (chunks not supported yet)
        fixed_headers = self.fix_content_length(headers, len(fixed_data))
        fixed_headers = self.fix_http_version(fixed_headers)
        if fixed_headers == False:
            log('::::::::: MALFORMED REQUEST MISSING HTTP VERSION HEADER ::::'+
                ':::::', self.logfile)
            return False
        fixed_headers = fixed_headers + '\r\n' + \
            '\r\n'.join(self.request_extra_headers)
        # assemble the request
        fixed_request = fixed_headers + '\r\n\r\n' + fixed_data
        # log('::::::::: REQUEST TO TARGET %s:%s' % self.target.getpeername() +
        # ' ::::\n%s\n::::::::::' % (fixed_request))
        log('::::::::: REQUEST TO TARGET %s:%s' % self.target.getpeername() +
            ' ::::\n%s\n%d\n::::::::::' % (fixed_headers, len(fixed_data)), 
            self.logfile)
        return fixed_request

    def get_response(self):
        """
        get the response from the target, parse the headers and the data and 
        return the parsed response.

        """
        log('get_response', self.logfile)
        headers, data = self.get_headers(conn=self.target, old_data='')
        log("Got response headers", self.logfile)
        log(headers, self.logfile)
        content_length = self.get_content_length(headers)
        if not content_length or content_length == 'chunked':
            data = self.get_data(conn=self.target, length=content_length,
                                old_data=data)
        elif len(data) < content_length:
            data = self.get_data(conn=self.target, length=content_length,
                                old_data=data)
        # log('::::::::: RESPONSE FROM TARGET  %s:%s' % 
        #       self.target.getpeername() + '::::\n%s\n::::::::::' % 
        #       (headers + '\r\n\r\n' + data))
        log('::::::::: RESPONSE FROM TARGET  %s:%s' % 
            self.target.getpeername() + 
            '::::\n%s\n%d\n::::::::::' % (headers , len(data)),
            self.logfile)
        # parse the data and make the substitutions
        if data: 
            fixed_data = self.parse_data(data, self.response_regexps)
        else: 
            fixed_data = data
        # fix the content lenght if necessary and add the aditional haeders
        if headers:
            fixed_headers = self.fix_content_length(headers, len(fixed_data))
        else:
            fixed_headers = headers
        fixed_headers = self.fix_http_version(fixed_headers)
        if fixed_headers == False:
            log('::::::::: MALFORMED RESPONSE MISSING HTTP VERSION HEADER' +
                ':::::::::', self.logfile)
            return False
        fixed_headers = fixed_headers + '\r\n' + \
                        '\r\n'.join(self.response_extra_headers)
        # assemble the response
        fixed_response = fixed_headers + '\r\n\r\n' + fixed_data
        # log('::::::::: RESPONSE TO CLIENT %s:%s' % self.client.getpeername() +
        #       '::::\n%s\n::::::::::' % (fixed_response))
        log('::::::::: RESPONSE TO CLIENT %s:%s' % self.client.getpeername() +
            '::::\n%s\n%d\n::::::::::' % (fixed_headers, len(fixed_data)),
            self.logfile)
        return fixed_response

    def fix_content_length(self, headers, new_length):
        """
        Given the new content length, fig the header content length.

        """
        log('fix_content_length', self.logfile)
        pattern = r'Content-Length: \d+'
        return re.sub(pattern, 'Content-Length: %d' % new_length, headers)

    def fix_http_version(self, headers):
        """
        Replace the HTTP/X.XX header for the HTTP/1.0, the only supprted version
        of HTTP.

        """
        log('fix_http_version', self.logfile)
        pattern = r'HTTP/[\d].[\d]*'
        result = re.search(pattern, headers)
        if result:
            return re.sub(pattern, 'HTTP/1.0', headers)
        else:
            return False

    def parse_data(self, data, regexps):
        """
        Apply the regexps to the data.

        """
        log('parse_data', self.logfile)
        fixeddata = data
        for regexp, substitute in regexps:
            fixeddata = re.sub(regexp, substitute, fixeddata)
        return fixeddata
              
    def get_request_method(self):
        """
        Get the request method, only GET and POST are supported yet.

        """
        log('get_request_method', self.logfile)
        data = self.client.recv(BUFLEN)
        method = data.split(' ', 1)[0]
        return method, data

    def get_content_length(self, headers):
        """
        Get the content length.
        returns close if the Connection: close header is present, chunked if the
        Transfer-Encoding is chunked or the content length.

        """
        log('get_content_length', self.logfile)
        result_length = re.search('Content-Length: (?P<content_length>\d+)', 
                                    headers)
        if result_length:
            content_length = int(result_length.group('content_length'))
        else:
            result_close = re.search('Connection: (?P<close>close)', headers)
            if result_close:
                content_length = 'close'
            else:
                result_type = re.search(
                                'Transfer-Encoding: (?P<encoding>chunked)',
                                 headers)
                if result_type:
                    content_length = 'chunked'
                else:
                    content_length = None
        log("Got content-length%s:" % content_length, self.logfile)
        return content_length

    def print_oct(self, string):
        """
        Prints the input in octal, for debugging.

        """
        log(string, self.logfile)
        for char in string:
            log('-%s-' % ord(char), self.logfile)
    
    def get_headers(self, conn, old_data):
        """
        Recover the headers, return the headers and the rest of the read data.

        """
        log('get_headers', self.logfile)
        headers = old_data
        newdata = ''
        end = headers.find('\r\n\r\n') 
        if end == -1: 
            end = headers.find('\n\n')
        #log('end=%d' % end, self.logfile)
        #self.print_oct(headers)
        if end >= 0:
            return headers[:end], headers[end+4:]
        while 1:
            newdata = conn.recv(BUFLEN)
            headers += newdata
            end = headers.find('\r\n\r\n')
            if end == -1: 
                end = headers.find('\n\n')
            #log('end=%d' % end, self.logfile)
            #self.print_oct(headers)
            if end >= 0 : 
                break
        return headers[:end], headers[end+4:]

    def get_chunk(self, conn, data):
        """
        TODO
        Must get the next chunk of the HTTP transmission and return the chunk and 
        the rest of the readen data.
        
        """
        log('get_chunk', self.logfile)
        end = data.find('\r\n')
        while end == -1:
            data += conn.recv(BUFLEN)
            end = data.find('\r\n')
        headers = data[:end]
        length = int(headers, 16)
        log("Got chunk of %d bytes:" % length, self.logfile)
        if length == 0:
            return headers, False
        body = data[end+2]
        while len(body) < length + 2:
            body += conn.recv(length + 2 - len(body))
        log("%d" % len(body[:length]), self.logfile)
        return headers + '\r\n' + body[:length], body[length + 2:] 

    def get_data(self, conn, length=None, old_data=''):
        """
        Gets the remaining data, using the content length, waiting for the 
        connection to end or (TODO) using the chunked protocol.

        """
        log('get_data', self.logfile)
        data = old_data
        if length == 'chunked':
        # this means that the server will use http1.1 chunk protocol to send the
        # response
            log('get_data::length=chunked', self.logfile)
            chunk, next_data = self.get_chunk(conn, data)
            data = chunk
            while next_data != False: 
                chunk, next_data = self.get_chunk(conn, next_data)
                data += chunk
        elif length == 'close':
        # this means that the server will close the connection, so we have to 
        # read everything we can.
            log('get_data::length=close', self.logfile)
            while 1:
                newdata = conn.recv(BUFLEN)
                data = data + newdata
                if not newdata: 
                    break
        elif length == None:
        # This means that the server did not send a Content-Length header and 
        # did not specify content-transer chunked nor connection: close, usually
        # a malformed response.
            log('get_data::length=None', self.logfile)
            while 1:
                newdata = conn.recv(BUFLEN)
                data += newdata
                if len(newdata) < BUFLEN: 
                    break
        else:
        # The server sent a Content-Length header so we read the specified
        # amount od words.
            log('get_data::length=%s' % length, self.logfile)
            while len(data) < length:
                data += conn.recv(length - len(data))
        return data

    def connect_to_target(self):
        """
        Connects to the target machine.

        """
        log('connect_to_target', self.logfile)
        (soc_family, _, _, _, address) = socket.getaddrinfo(self.remote_host, 
                                                self.remote_port)[0]
        target = socket.socket(soc_family)
        target.settimeout(60.0)
        if self.remote_proto == 'https':
            try:
                target = ssl.wrap_socket(target)
            except Exception, exc:
                log("::::::::: ERROR :::: Exception encountered attending" + \
                        "remote %s:%d." % (self.remote_host, self.remote_port),
                        self.logfile)
                print exc
                target.shutdown(socket.SHUT_RDWR)
                target.close()
                return None
        target.connect(address)
        return target


class Tunnel:
    """
    This class is the pupeteer master, the one that receives the connections and
    launches the threads.

    """
    def __init__(self, max_threads=100, 
            main_logfile='tunnel-main-sample.log', 
            threads_logfile='tunnel-threads-sample.log',
            local_port=8888, local_ip='127.0.0.1', local_proto='http', 
            remote_port=8080, remote_host='127.0.0.1', remote_proto='http',
            local_cert='server.crt', local_key='server.key',
            remote_cert='server.crt', remote_key='server.key',
            request_extra_headers='', response_extra_headers='',
            request_regexps=None, response_regexps=None,
            ipv6=False, timeout=60):
        self.logfile = open(main_logfile,'a')
        sys.stdout.flush()
        self.local_port = int(local_port)
        self.local_ip = local_ip
        self.local_proto = local_proto
        self.remote_port = int(remote_port)
        self.remote_host = remote_host
        self.remote_proto = remote_proto
        self.local_cert = local_cert
        self.local_key = local_key
        self.remote_cert = remote_cert
        self.remote_key = remote_key
        self.request_extra_headers = request_extra_headers
        self.response_extra_headers = response_extra_headers
        self.request_regexps = request_regexps or []
        self.response_regexps = response_regexps or []
        self.ipv6 = ipv6
        self.timeout = timeout
        self.sock = None
        self.max_threads = max_threads
        self.threads_logfile = threads_logfile

        log("Starting thread server at %s://%s:%s --> %s://%s:%s" % \
                ( local_proto, local_ip, local_port, 
                    remote_proto, remote_host, remote_port),
                self.logfile, 'CRIT')
        self.run()

    def run(self, handler=ConnectionHandler):
        """
        Main loop, just listen for connections and spawn threads as availaible.

        """
        if self.ipv6 == True:
            sock_type = socket.AF_INET6
        else:
            sock_type = socket.AF_INET
        
        try:
            self.sock = socket.socket(sock_type)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.local_ip, self.local_port))
            log("Serving on %s:%d." % (self.local_ip, self.local_port), 
                 self.logfile, 'CRIT')
            self.sock.listen(5)
            while 1:
                try:
                    count = 0
                    while threading.activeCount() > self.max_threads:
                        count = count+1
                        time.sleep(0.1)
                        if count == self.max_threads:
                            log("Max threads reached... waiting for someone " +
                                "to end...",self.logfile)
                            count = 0
                    newconn, addr = self.sock.accept()
                    log('Connected from %s:%d' % addr, self.logfile)
                    if self.local_proto == 'https':
                        try:
                            conn = ssl.wrap_socket(newconn, 
                                    certfile=self.local_cert, 
                                    keyfile=self.local_key, 
                                    server_side=True)
                        except Exception, exc:
                            log("Error while trying to wrap the ssl " +
                                "connection with %s:%d:\n%s" % (addr[0], 
                                                                addr[1], 
                                                                exc), 
                                        self.logfile)
                            log("closing", self.logfile)
                            newconn.send('ERROR:wrong proto!')
                            newconn.shutdown(socket.SHUT_RDWR)
                            newconn.close()
                            log("closed", self.logfile)
                            continue
                    else:
                        conn = newconn
                    log('Threads running:%d' % threading.activeCount(), 
                            self.logfile)
                    newthread = threading.Thread(target=handler, 
                            args=(self.threads_logfile, conn,  
                                    self.remote_host, self.remote_port,
                                    self.local_proto, self.remote_proto,
                                    self.remote_cert, self.remote_key,
                                    self.request_regexps, self.response_regexps,
                                    self.request_extra_headers, 
                                    self.response_extra_headers))
                    newthread.start()
                except KeyboardInterrupt:
                    break
                except Exception, exc:
                    log("ERROR on main loop", self.logfile, 'CRIT')
                    log('%s' % exc, self.logfile, 'CRIT')
        finally:
            self.stop()
    
    def stop(self):
        """
        Clean up.

        """
        log("waiting for threads to end", self.logfile)
        log("Threads still alive:\n\t", self.logfile)
        for thread in threading.enumerate():
            log("\tThread %s" % thread.getName(), self.logfile)
        log("Stopping..", self.logfile)
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
        except:
            pass
        self.logfile.close()


def parse_config(conf_file):
    """
    Parse the config files but use some default values.

    """
    config = ConfigParser.SafeConfigParser(
                {'max_threads': '100',
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
                'response_regexps':'',
                'request_extra_headers': 'X-Tunneled-From: %(local_proto)' + \
                        '://%(local_ip):%(local_port)',
                'response_extra_headers': 'X-Tunneled-To: %(remote_proto' + \
                        ')://%(remote_host):%(remote_port)'})
    config.read(conf_file)
    for section in config.sections():
        ### todo, launch a thread for each section, not only the first one.
        max_threads = config.get(section, 'max_threads')
        main_logfile = config.get(section, 'main_logfile')
        threads_logfile = config.get(section, 'threads_logfile')
        local_port  = config.get(section, 'local_port')
        local_ip = config.get(section, 'local_ip')
        local_proto = config.get(section, 'local_proto')
        local_cert = config.get(section, 'local_cert')
        local_key = config.get(section, 'local_key')
        remote_port = config.get(section, 'remote_port')
        remote_host = config.get(section, 'remote_host')
        remote_proto = config.get(section, 'remote_proto')
        remote_cert = config.get(section, 'remote_cert')
        remote_key = config.get(section, 'remote_key')
        request_extra_headers = [
            header.strip() for header in config.get(section, 
                                           'request_extra_headers').split(',')]
        response_extra_headers = [
            header.strip() for header in config.get(section, 
                                           'response_extra_headers').split(',')]
        request_regexps = [
            tuple(pair.split(':')) for pair in config.get(section, 
                                            'request_regexps').split(',')]
        if request_regexps == [('',)]: 
            request_regexps = []
        response_regexps = [ 
            tuple(pair.split(':')) for pair in config.get(section, 
                                            'response_regexps').split(',')]
        if response_regexps == [('',)]: 
            response_regexps = []
        server = Tunnel(max_threads=max_threads,
                        main_logfile=main_logfile,
                        threads_logfile=threads_logfile,
                        local_port=local_port, 
                        local_ip=local_ip, 
                        local_proto=local_proto,
                        local_cert=local_cert, 
                        local_key=local_key,
                        remote_port=remote_port, 
                        remote_host=remote_host, 
                        remote_proto=remote_proto,
                        remote_cert=remote_cert, 
                        remote_key=remote_key,
                        request_extra_headers=request_extra_headers, 
                        response_extra_headers=response_extra_headers,
                        request_regexps=request_regexps, 
                        response_regexps=response_regexps)
        return server

def create_sample_config(conf_file):
    """
    Create a sample config file with some default values, just for guidance.

    """
    config = ConfigParser.RawConfigParser()
    config.add_section('Sample')
    config.set('Sample', 'main_logfile', 'tunnel-main-sample.log')
    config.set('Sample', 'threads_logfile', 'tunnel-threads-sample.log')
    config.set('Sample', 'max_threads', '100')
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
    config.set('Sample', 'request_extra_headers', 
            'X-Tunneled-From: %(local_proto)s://%(local_ip)s:%(local_port)s')
    config.set('Sample', 'response_extra_headers', 
            'X-Tunneled-To: %(remote_proto)s://%(remote_host)s:%(remote_port)s')
    config.set('Sample', 'request_regexps', 'regexp1:subst1,regexp2:subst2')
    config.set('Sample', 'response_regexps', 'regexp1:subst1,regexp2:subst2')
    configfile = open(conf_file, 'wb')
    try:
        config.write(configfile)
    finally:
        configfile.close()
    

def main():
    '''
    Main routine, parses the config and  starts the Tunnel class.

    '''
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
    parser.add_argument('--create_config', action='store_true', 
        default=False, help='Create a sample config file')
    parser.add_argument('--max_threads', default=100, type=int,
        help='Max number of simultaneous threads to launch (100 by default).')

    args = parser.parse_args()
    
    if args.create_config:
        if not os.path.isfile(CONFFILE):
            print "Sample config file created at %s" % CONFFILE
            create_sample_config(CONFFILE)
        else:
            print "Config file %s already exists." % CONFFILE
        sys.exit(0)

    global DEBUG
    DEBUG = args.debug

    try:
        if args.config:
            if os.path.isfile(args.config):
                parse_config(args.config)
            else:
                print "Config file %s not found..." % args.config
                sys.exit(0)
        else:
            max_threads = args.max_threads
            local_ip = args.local_ip
            local_port = args.local_port
            remote_host = args.remote_host
            remote_port = args.remote_port
            server = Tunnel(max_threads=max_threads,
                            local_ip=local_ip, 
                            local_port=local_port,
                            remote_host=remote_host, 
                            remote_port=remote_port)
    except KeyboardInterrupt:
        print "Exiting."
     

if __name__ == '__main__':
    main()
