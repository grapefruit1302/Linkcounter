from easysnmp import Session
from zabbix_utils import get_switch_ip

class SwitchFactory:
    def create_switch(self, ip, core_mac_dict, zabbix_url, zabbix_user, zabbix_password):
        self.ip = ip
        self.community_string = 'public'
        self.version = 2
        self.core_mac_address = core_mac_dict
        self.zabbix_url= zabbix_url
        self.zabbix_user = zabbix_user
        self.zabbix_password = zabbix_password

        # print(ip)

        model_oid = "1.3.6.1.2.1.1.1.0"  
        self.session = Session(hostname=self.ip, community=self.community_string, version=self.version)
        model_value = self.session.get(model_oid).value
        print(model_value)
        if "D-Link" in model_value or "DES" in model_value or "DGS" in model_value:
            return Dlink(self.ip, self.community_string, self.version, self.core_mac_address, self.zabbix_url, self.zabbix_user, self.zabbix_password)
        else:
            return None

class BDCOM_EPON:
    def __init__(self, ip_address, community, version, core_mac_address, zabbix_url, zabbix_user, zabbix_password):
        self.ip = ip_address
        self.community_string = community
        self.version = version
        self.core_mac_address = core_mac_address
        self.zabbix_url= zabbix_url
        self.zabbix_user = zabbix_user
        self.zabbix_password = zabbix_password

        self.snmp_oid_active_onu = "1.3.6.1.4.1.3320.101.6.1.1.21."
        self.snmp_oid_status_port = "1.3.6.1.2.1.2.2.1.8."
        self.snmp_oid_port_description = "1.3.6.1.2.1.2.2.1.2."
        self.snmp_oid_mac_port = "1.3.6.1.2.1.17.7.1.2.2.1.2."

        self.session = Session(hostname=self.ip, community=community, version=self.version)

        # В розробці

class Dlink:
    def __init__(self, ip_address, community, version, core_mac_address, zabbix_url, zabbix_user, zabbix_password):
        self.ip = ip_address
        self.community_string = community
        self.version = version
        self.core_mac_address = core_mac_address
        self.zabbix_url= zabbix_url
        self.zabbix_user = zabbix_user
        self.zabbix_password = zabbix_password

        self.snmp_oid_status_port = "1.3.6.1.2.1.31.1.1.1.1."
        self.snmp_oid_all_interfaces = "1.3.6.1.2.1.2.2.1.8."
        self.snmp_oid_port_description = "1.3.6.1.2.1.31.1.1.1.18."
        self.snmp_oid_mac_port = "1.3.6.1.2.1.17.7.1.2.2.1.2."

        self.session = Session(hostname=self.ip, community=community, version=self.version)

    def get_number_ports(self):
        all_interfaces = self.session.walk(self.snmp_oid_status_port)
        port_numbers = [int(port.value.split('/')[1]) for port in all_interfaces if '/' in port.value and port.value.count('/') == 1]
        return max(port_numbers) if port_numbers else 0

    def get_status_ports(self):
        port_status_dict = {}
        for i, port in enumerate(range(1, self.get_number_ports() + 1), start=1):
            status_port = self.session.get(self.snmp_oid_all_interfaces + str(port)).value
            port_status = "up" if status_port == '1' else "down"
            port_status_dict[i] = port_status

        return port_status_dict

    def get_description_ports(self, port):
        port_description_dict = {}
        for i in range(1, self.get_number_ports() + 1):
            description_all_ports = self.session.get(self.snmp_oid_port_description + str(i)).value
            port_description = self._classify_port_description(description_all_ports)
            port_description_dict[i] = port_description

        return port_description_dict if port == 'All' else port_description_dict.get(port)

    def _classify_port_description(self, description):
        if "client" in description or "tr_" in description:
            return "client"
        elif "sw-" in description or "gw-" in description or "sr-te" in description:
            return description
        else:
            return None

    def get_mac_ports(self):
        port_mac_dict = {}
        mac_all_ports = self.session.walk(self.snmp_oid_mac_port)

        for var in mac_all_ports:
            port_number = int(var.value)
            mac_address_oid = var.oid.split('.')[-6:]
            mac_address_list = [int(x) for x in mac_address_oid]
            mac_address_str = ':'.join(['{:02X}'.format(x) for x in mac_address_list])
            if port_number not in port_mac_dict:
                port_mac_dict[port_number] = []

            port_mac_dict[port_number].append(mac_address_str)

        return port_mac_dict

    def search_uplink(self):
        uplink_port_data = {}
        mac_ports = self.get_mac_ports()

        for port, mac_list in mac_ports.items():
            if any(core_mac in mac_list for core_mac in self.core_mac_address):
                uplink_port_data[port] = self.get_description_ports(port)
                return uplink_port_data

        return None
    
    def get_switches(self):
        port_descriptions = self.get_description_ports("All")
        uplink_data = self.search_uplink()

        uplink_description = list(uplink_data.values())[0] if uplink_data else None
        switch_names = [desc for desc in port_descriptions.values() if desc and ("sw-" in desc or "gw-" in desc or "sr-te" in desc) and desc != uplink_description]

        return get_switch_ip(zabbix_url, zabbix_user, zabbix_password, switch_names)

    def count_active_user(self):
        number_ports = self.get_number_ports()
        status_ports = self.get_status_ports()
        description_ports = self.get_description_ports('All')

        active_user_count = 0

        for port in range(1, number_ports + 1):
            status = status_ports.get(port)
            description = description_ports.get(port)
            if status == 'up' and description is not None and description.lower() == 'client':
                active_user_count += 1

        return active_user_count
    

ip = "10.69.109.74"
community_string = "public"
version = 2
core_mac_dict = {'88:90:09:FE:C4:6D', '88:90:09:FE:C4:6E'}
zabbix_url = 'https://zabbix6.columbus.te.ua'
zabbix_user = 'yu.petrovskyi'
zabbix_password = '7N2_55c!vDg@Kc'

def traverse_switch_hierarchy(current_ip):
    active_users = 0

    switch_factory = SwitchFactory()
    switch_object = switch_factory.create_switch(current_ip, core_mac_dict, zabbix_url, zabbix_user, zabbix_password)

    if switch_object != None:
        

        active_user_count = switch_object.count_active_user()
        active_users += active_user_count

        lower_switch_ips = switch_object.get_switches()
        for lower_switch_ip in lower_switch_ips:
            traverse_switch_hierarchy(lower_switch_ips[lower_switch_ip])
        
    return active_users


print(traverse_switch_hierarchy(ip))
