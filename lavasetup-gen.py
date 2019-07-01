#!/usr/bin/env python
#
from __future__ import print_function
import os, sys, time
import subprocess
import stat
import yaml
import string
import socket
import shutil
import argparse
import jinja2
import pathlib
import logging

#no comment it is volontary
template_device = string.Template("""{% extends '${devicetype}.jinja2' %}
""")

def logger_create(name, stream=None):
    logger = logging.getLogger(name)
    loggerhandler = logging.StreamHandler(stream=stream)
    loggerhandler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(loggerhandler)
    logger.setLevel(logging.INFO)
    return logger

def logger_setup_color(logger, color='auto'):
    from bb.msg import BBLogFormatter
    console = logging.StreamHandler(sys.stdout)
    formatter = BBLogFormatter("%(levelname)s: %(message)s")
    console.setFormatter(formatter)
    logger.handlers = [console]
    if color == 'always' or (color=='auto' and console.stream.isatty()):
        formatter.enable_color()

logger = logger_create(sys.argv[0], stream=sys.stdout)


def sanitize_master(entry):

    sanitize_entry = entry

    keywords = [ "name", "type", "host", "users", "groups", "postgre_password", "logger_port", "master_port", "postgre_user", "postgre_hostname", "zmq_auth_key", "zmq_auth_key_secret", "zmq_auth", "server_port", "dns_name"]
    for keyword in entry:
        if not keyword in keywords:
            logger.error("ERROR: unknown keyword %s" % keyword)
            sys.exit(1)

    if not "postgre_password" in entry:
        logger.error("Missing postgre password entry for master")
        sys.exit(1)

    if not "name" in entry:
        sanitize_entry["name"] = "master"
    else:
        sanitize_entry["name"] = entry["name"]

    if not "host" in entry:
        sanitize_entry["host"] = "local"
    else:
        sanitize_entry["host"] = entry["host"]

    if not "logger_port" in entry:
        sanitize_entry["logger_port"] = "5555"
    else:
        sanitize_entry["logger_port"] = entry["logger_port"]

    if not "master_port" in entry:
        sanitize_entry["master_port"] = "5556"
    else:
        sanitize_entry["master_port"] = entry["master_port"]

    if not "postgre_user" in entry:
        sanitize_entry["postgre_user"] = "lavaserver"
    else:
        sanitize_entry["postgre_user"] = entry["postgre_user"]

    if not "postgre_hostname" in entry:
        sanitize_entry["postgre_hostname"] = "database"
    else:
        sanitize_entry["postgre_hostname"] = entry["postgre_hostname"]

    return sanitize_entry

def sanitize_slave(entry):

    sanitize_entry = entry

    keywords = [ "name", "type", "host", "users", "groups", "remote_master", "zmq_auth_key", "zmq_auth_key_secret", "zmq_auth"]
    for keyword in entry:
        if not keyword in keywords:
            logger.error("ERROR: unknown keyword %s" % keyword)
            sys.exit(1)

    if not "remote_master" in entry:
        logger.error("Missing remote master entry for slave")
        sys.exit(1)

    if not "name" in entry:
        sanitize_entry["name"] = "master"
    else:
        sanitize_entry["name"] = entry["name"]

    if not "host" in entry:
        sanitize_entry["host"] = "local"
    else:
        sanitize_entry["host"] = entry["host"]

    return sanitize_entry

def sanitize_user(entry):

    sanitize_entry = entry

    keywords = [ "name", "password", "superuser", "staff" ]
    for keyword in entry:
        if not keyword in keywords:
            logger.error("ERROR: unknown keyword %s" % keyword)
            sys.exit(1)

    if not "name" in entry:
        logger.error("Missing name for user entry")
        sys.exit(1)

    if not "password" in entry:
        logger.error("Missing password for user entry")
        sys.exit(1)

    if not "superuser" in entry:
        sanitize_entry["superuser"] = "no"
    else:
        sanitize_entry["superuser"] = entry["superuser"]

    if not "staff" in entry:
        sanitize_entry["staff"] = "no"
    else:
        sanitize_entry["staff"] = entry["staff"]

    return sanitize_entry


def found_slave(workers, name):
    found_slave = False
    worker = {}
    for worker in workers["slaves"]:
        if worker["name"] == name:
            slave = worker
            found_slave = True
    if not found_slave:
        logger.error("Cannot find slave %s" % worker_name)
        sys.exit(1)

    return worker

def get_master(masters, name):
    for master in masters:
        s_master = sanitize_master(master)
        if s_master["name"] == name:
            return s_master
    return {}

def get_slave(slaves, name):
    for slave in slaves:
        s_slave = sanitize_slave(slave)
        if s_slave["name"] == name:
            return s_slave
    return {}

def process_lava_slaves_host(workers, args):

    master_host = []
    for master in workers["masters"]:
        master_host.append(master["host"])

    if "slaves" not in workers:
        return

    slaves = workers["slaves"]
    masters = workers["masters"]
    hostname = socket.gethostname()

    for slave in slaves:
        s_slave = sanitize_slave(slave)
        host = s_slave["host"]
        if host in master_host:
            continue

        if args.only_hostname == True and host != hostname:
            continue

        master = get_master(masters, slave["remote_master"])

        if not os.path.isdir("output/%s" % host):
            os.mkdir("output/%s" % host)

        base_dir = pathlib.Path(__name__).parent
        conf_file_path = str(base_dir)+"/output/%s" %(host)
        logger.info("Create: %s" %(os.path.join(conf_file_path, "docker-compose.yml")))
        templates = base_dir / "templates"
        j2_env = jinja2.Environment(loader=jinja2.FileSystemLoader([str(templates)], followlinks=True), undefined=jinja2.StrictUndefined)

        context = {
            "LAVA_SERVER_HOSTNAME": master["dns_name"],
            "LAVA_SERVER_MASTER_PORT": master["master_port"],
            "LAVA_SERVER_LOGS_PORT": master["logger_port"],
            "DISPATCHER_HOSTNAME": slave["name"]
        }
        conf = j2_env.get_template('docker-compose_slave.jinja2')
        conf = conf.render(context)
        with open(os.path.join(conf_file_path, "docker-compose.yml"), 'w') as f:
            f.write(conf)

def copy_master_dockerfile(host):

    logger.info("Copy Dockerfile end entrypoint for master")

    base_dir = pathlib.Path(__name__).parent
    conf_file_path = str(base_dir)+"/output/%s/server-docker" %(host)

    templates = base_dir / "server-docker"
    shutil.copy(str(templates)+"/Dockerfile", conf_file_path)
    shutil.copy(str(templates)+"/entrypoint.sh", conf_file_path)


def copy_squid_configuration(host):

    logger.info("Copy Squid configuration")

    base_dir = pathlib.Path(__name__).parent
    conf_file_path = str(base_dir)+"/output/%s/squid" %(host)

    templates = base_dir / "squid"
    shutil.copy(str(templates)+"/squid.conf", conf_file_path)


def process_lava_server_master(workers, args):

    if "masters" not in workers:
        return (None, None)
    else:
        masters = workers["masters"]

    if len(masters) > 1:
        logger.error(" Only one master is supported")
        sys.exit(1)

    master = masters[0]
    s_master = sanitize_master(master)
    host = s_master["host"]
    hostname = socket.gethostname()

    if args.only_hostname == True and host != hostname:
        return (None, None)

    # Create relevant directory
    if not os.path.isdir("output/%s" % host):
        os.mkdir("output/%s" % host)

    path_list = [ "output/%s/server-overlay/etc/lava-server/dispatcher-config/devices" %host,
            "output/%s/server-overlay/etc/lava-server/dispatcher-config/health-checks" %host,
            "output/%s/server-overlay/root/entrypoint.d" %host,
            "output/%s/squid" %host,
            "output/%s/server-docker" %host ]

    for path in path_list:
        if not os.path.exists(path):
            os.makedirs(path)

    # Create context dictionary to resolve variable in jinja file
    context = {
    "LAVA_SERVER_DB_HOSTNAME": s_master["postgre_hostname"],
    "POSTGRES_USER": s_master["postgre_user"],
    "POSTGRES_PASSWORD": s_master["postgre_password"],
    "LAVA_SERVER_HOSTNAME": s_master["name"],
    "LAVA_SERVER_DNS_HOSTNAME": s_master["dns_name"],
    "LAVA_SERVER_HOST_PORT": s_master["server_port"],
    "LAVA_SERVER_MASTER_PORT": s_master["master_port"],
    "LAVA_SERVER_LOGS_PORT": s_master["logger_port"],
    "LAVA_SERVER_OVERLAY_PATH": "./server-overlay"
    }

    # Copy Squid configuration
    copy_squid_configuration(host)


    # Copy master instance.conf
    base_dir = pathlib.Path(__name__).parent
    conf_file_path = str(base_dir)+"/output/%s/server-overlay/etc/lava-server" %(host)
    templates = base_dir / "server-overlay/etc/lava-server"

    logger.info("Copy: %s" %(os.path.join(conf_file_path, "env.yaml")))
    shutil.copy(str(templates)+"/env.yaml", conf_file_path)


    logger.info("Create: %s" %(os.path.join(conf_file_path, "instance.conf")))

    # Resolve instance.jinja2 template with variables
    templates = base_dir / "server-overlay/etc/lava-server"
    j2_env = jinja2.Environment(loader=jinja2.FileSystemLoader([str(templates)], followlinks=True), undefined=jinja2.StrictUndefined)

    conf = j2_env.get_template('instance.jinja2')
    conf = conf.render(context)

    with open(os.path.join(conf_file_path, "instance.conf"), 'w') as f:
        f.write(conf)

    # Copy settings.conf
    logger.info("Create: %s" %(os.path.join(conf_file_path, "settings.conf")))
    conf = j2_env.get_template('settings.jinja2')
    conf = conf.render(context)

    with open(os.path.join(conf_file_path, "settings.conf"), 'w') as f:
        f.write(conf)

    return s_master, context


def process_lava_server_slaves(workers, master, context):

    master_host = master["host"]
    base_dir = pathlib.Path(__name__).parent
    conf_file_path = str(base_dir)+"/output/%s" %(master_host)
    logger.info("Create: %s" %(os.path.join(conf_file_path, "docker-compose.yml")))


    if "slaves" not in workers:
        slaves = {}
    else:
        slaves = workers["slaves"]

    found_slave = False
    master_slave = {}
    for slave in slaves:
        s_slave = sanitize_slave(slave)
        if s_slave["host"] == master_host:
            logger.info("Master has slave")
            if found_slave == True:
                logger.error("Master can support only one slave")
                sys.exit(1)
            else:
                found_slave = True
            context["HAVE_SLAVE"] = "true"
            context["DISPATCHER_HOSTNAME"] = s_slave["name"]
            master_slave = s_slave

    templates = base_dir / "templates"
    j2_env = jinja2.Environment(loader=jinja2.FileSystemLoader([str(templates)], followlinks=True), undefined=jinja2.StrictUndefined)

    conf = j2_env.get_template('docker-compose_master.jinja2')
    conf = conf.render(context)
    with open(os.path.join(conf_file_path, "docker-compose.yml"), 'w') as f:
        f.write(conf)

def process_lava_server_boards(workers, master):


    master_host = master["host"]

    base_dir = pathlib.Path(__name__).parent
    conf_file_path = str(base_dir)+"/output/%s/server-overlay/etc/lava-server/dispatcher-config/devices" %(master_host)

    if found_slave == False:
        boards = {}
    elif "boards" not in workers:
        boards = {}
    else:
        boards = workers["boards"]

    for board in boards:
        board_name = board["name"]
        if "slave" not in board:
            logger.error("Missing slave information for board: %s" %board_name)
            sys.exit(1)

        if "type" not in board:
            logger.error("Missing board type information for board: %s" %board_name)
            sys.exit(1)

        worker_name = board["slave"]
        master_slave = get_slave(workers['slaves'], worker_name)
        if not master_slave:
            logger.error("Slave not existing: %s" %worker_name)
            sys.exit(1)

        if worker_name == master_slave["name"]:
            devicetype = board["type"]
            device_line = template_device.substitute(devicetype=devicetype)

            if "options" in board:
                if type(board["options"]) == list:
                    for coption in board["options"]:
                        device_line += "{%% %s %%}\n" % coption
                else:
                    for line in board["options"].splitlines():
                        device_line += "{%% %s %%}\n" % line


            board_device_file = os.path.join(conf_file_path, board_name+".jinja2")
            logger.info("Create device dictionary: %s" %(board_device_file))
            fp = open(board_device_file, "w")
            fp.write(device_line)
            fp.close()

def process_lava_server_provision_script(workers, master):

    users=[]

    base_dir = pathlib.Path(__name__).parent
    master_host = master["host"]

    for user in master["users"]:
        s_user = sanitize_user(user)
        users.append(s_user)

    context = {
        "USERS": users,
        "BOARDS": workers["boards"],
    }
    templates = base_dir / "server-overlay/root"
    j2_env = jinja2.Environment(loader=jinja2.FileSystemLoader([str(templates)], followlinks=True), undefined=jinja2.StrictUndefined)
    conf = j2_env.get_template('provision.jinja2')
    conf = conf.render(context)
    conf_file_path = str(base_dir)+"/output/%s/server-overlay/root/entrypoint.d" %(master_host)
    provision_device_file = os.path.join(conf_file_path, "provision.sh")
    logger.info("Create device provision script: %s" %(provision_device_file))
    with open(provision_device_file, 'w') as f:
        f.write(conf)
    st = os.stat(provision_device_file)
    os.chmod(provision_device_file, st.st_mode | stat.S_IEXEC)

def process_lava_server_healthcheck_job(master):

    logger.info("Copy health-check jobs")
    base_dir = pathlib.Path(__name__).parent
    master_host = master["host"]
    templates = base_dir / "server-overlay/etc/lava-server/dispatcher-config/health-checks"
    conf_file_path = str(base_dir)+"/output/%s/server-overlay/etc/lava-server/dispatcher-config/health-checks" %(master_host)
    shutil.copy(str(templates)+"/qemu.yaml", conf_file_path)

def process_lava_server_host_configuration(workers, args):
    master, context = process_lava_server_master(workers, args)

    if master:
        process_lava_server_slaves(workers, master, context)
        process_lava_server_boards(workers, master)
        process_lava_server_provision_script(workers, master)
        process_lava_server_healthcheck_job(master)

def main():

    parser = argparse.ArgumentParser(description='Generate LAVA host setup')

    parser.add_argument('-v', '--verbose', default=0,
            dest='verbose', metavar='level', type=int,
            help="Increase verbosity level: 0 = ERROR, 1 = WARNING, 2 = INFO, 3 = DEBUG. (default: ERROR)")

    parser.add_argument('-o', '--only-hostname',
        action='store_true', dest="only_hostname",
        help="Generate configuration only for current hostnmae", default=False)

    parser.add_argument('-f', '--filename',
        dest="lava_setup_yaml", metavar='filename', type=str, default="lava_setup.yaml",
        help="LAVA setup description file")

    args = parser.parse_args()

    # Configure logger for requested verbosity.
    if args.verbose == 0:
        logger.setLevel(logging.ERROR)
    elif args.verbose == 1:
        logger.setLevel(logging.WARNING)
    elif args.verbose == 2:
        logger.setLevel(logging.INFO)
    elif args.verbose == 3:
        logger.setLevel(logging.DEBUG)


    need_zmq_auth_gen = False
    fp = open(args.lava_setup_yaml, "r")
    workers = yaml.load(fp)
    fp.close()

    os.mkdir("output")

    process_lava_server_host_configuration(workers, args)

    process_lava_slaves_host(workers, args)


if __name__ == '__main__':
    try:
        ret =  main()
    except Exception:
        ret = 1
        import traceback
        traceback.print_exc()
    sys.exit(ret)
