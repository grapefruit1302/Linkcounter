from pyzabbix import ZabbixAPI

def get_switch_ip(zabbix_url, zabbix_user, zabbix_password, switch_names):
    zabbix = ZabbixAPI(zabbix_url)
    zabbix.login(zabbix_user, zabbix_password)

    switch_ips = {}
    for switch_name in switch_names:
        node = zabbix.host.get(filter={'host': switch_name}, selectInterfaces=['ip'])
        if node and 'interfaces' in node[0]:
            switch_ip = node[0]['interfaces'][0]['ip']
            switch_ips[switch_name] = switch_ip

    return switch_ips
