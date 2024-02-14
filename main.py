from easysnmp import Session, EasySNMPError, EasySNMPTimeoutError
from zabbix_utils import get_switch_ip, get_zabbix_triggers, transform_host_name, get_region
from billing_utils import add_TD, close_TD
import datetime
import struct
import re
import time
import configparser

class SwitchFactory:
    def create_switch(self, ip, core_mac_dict, zabbix_url, zabbix_user, zabbix_password):
        self.ip = ip
        self.community_string = 'public'
        self.version = 2
        self.core_mac_address = core_mac_dict
        self.zabbix_url= zabbix_url
        self.zabbix_user = zabbix_user
        self.zabbix_password = zabbix_password

        try:
            # Виконати підключення до комутатора
            model_oid = "1.3.6.1.2.1.1.1.0"
            self.session = Session(hostname=self.ip, community=self.community_string, version=self.version)
            model_value = self.session.get(model_oid).value
            print(model_value)
            
            # Перевірити тип комутатора і повернути відповідний об'єкт
            if "D-Link" in model_value or "DES" in model_value or "DGS" in model_value:
                return Dlink(self.ip, self.community_string, self.version, self.core_mac_address, self.zabbix_url, self.zabbix_user, self.zabbix_password)
            elif "ECS" in model_value or "Edge" in model_value:
                return Edge_Core(self.ip, self.community_string, self.version, self.core_mac_address, self.zabbix_url, self.zabbix_user, self.zabbix_password)
            elif "BDCOM" in model_value and "GP3600" in model_value: 
                return BDCOM(self.ip, self.community_string, self.version, self.core_mac_address, self.zabbix_url, self.zabbix_user, self.zabbix_password, "GPON")
            elif "BDCOM" in model_value and "GP3600" not in model_value and "3310B" not in model_value: 
                return BDCOM(self.ip, self.community_string, self.version, self.core_mac_address, self.zabbix_url, self.zabbix_user, self.zabbix_password, "EPON")
            elif "BDCOM" in model_value and "3310B" in model_value: 
                return BDCOM(self.ip, self.community_string, self.version, self.core_mac_address, self.zabbix_url, self.zabbix_user, self.zabbix_password, "3310B")
            elif "MGS" in model_value: 
                return Zyxel(self.ip, self.community_string, self.version, self.core_mac_address, self.zabbix_url, self.zabbix_user, self.zabbix_password)
            else:
                return None

        except EasySNMPError as e:
            # Опрацювати помилку EasySNMPError
            print("Помилка EasySNMP: ", e)
            return None
        except TimeoutError:
            # Обробити помилку зв'язку
            print("Комутатор недоступний (timed out while connecting to remote host).")
            return None
            
class BDCOM_LOC_POW:
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
        self.snmp_oid_port_description = "1.3.6.1.2.1.31.1.1.1.18."
        self.snmp_oid_mac_port = "1.3.6.1.2.1.17.7.1.2.2.1.2."
        self.snmp_oid_all_interfaces = "1.3.6.1.2.1.31.1.1.1.1."
        self.snmp_oid_onu_status = '1.3.6.1.4.1.3320.101.10.1.1.26.'
        self.snmpoid_oid_all_onu = '1.3.6.1.4.1.3320.101.9.1.1.1.'
        self.snmp_oid_onu_lastderegtime = '1.3.6.1.4.1.3320.101.11.1.1.10'


        self.session = Session(hostname=self.ip, community=community, version=self.version, use_enums=True)

    def get_onu_dereg_time(self):
        deregistration_times = self.session.walk(self.snmp_oid_onu_lastderegtime)
        onu_dereg_time = {}

        for index, dereg_oid in enumerate(deregistration_times):
            dereg_variable = self.session.get(dereg_oid.oid)
            dereg_value = dereg_variable.value
            dereg_time = [ord(char) for char in dereg_value]
            dereg_year, dereg_month, dereg_day, dereg_hour, dereg_minute, dereg_second = struct.unpack('>HBBBBB', bytes(dereg_time[0:7]))
            dereg_time_str = f"{dereg_year}-{dereg_month:02d}-{dereg_day:02d} {dereg_hour:02d}:{dereg_minute:02d}:{dereg_second:02d}"
            mac_address_oid = dereg_oid.oid.split('.')[-6:]
            mac_address_list = [int(x) for x in mac_address_oid]
            mac_address_str = ':'.join(['{:02X}'.format(x) for x in mac_address_list])

            if mac_address_str not in onu_dereg_time:
                onu_dereg_time[mac_address_str] = []
            onu_dereg_time[mac_address_str] = dereg_time_str
        return onu_dereg_time
    

    def check_power_issues(self, device_data):
            registration_counts = {}
            current_time = datetime.datetime.now()

            for mac_address, registration_time_str in device_data.items():
                registration_time = datetime.datetime.strptime(registration_time_str, '%Y-%m-%d %H:%M:%S')
                if current_time - registration_time <= datetime.timedelta(minutes=10):
                    registration_time_floor = registration_time.replace(second=0, microsecond=0)
                    registration_counts[registration_time_floor] = registration_counts.get(registration_time_floor, 0) + 1

            for count in registration_counts.values():
                if count >= 2:
                    return True
            return False


class BDCOM:
    def __init__(self, ip_address, community, version, core_mac_address, zabbix_url, zabbix_user, zabbix_password, technology):
        self.ip = ip_address
        self.community_string = community
        self.version = version
        self.core_mac_address = core_mac_address
        self.zabbix_url= zabbix_url
        self.zabbix_user = zabbix_user
        self.zabbix_password = zabbix_password
        self.technology = technology

        self.snmp_oid_active_onu = "1.3.6.1.4.1.3320.101.6.1.1.21."
        self.snmp_oid_active_onu_gpon = "1.3.6.1.4.1.3320.10.2.1.1.4"
        self.snmp_oid_status_port = "1.3.6.1.2.1.2.2.1.8."
        self.snmp_oid_port_description = "1.3.6.1.2.1.31.1.1.1.18."
        self.snmp_oid_mac_port = "1.3.6.1.2.1.17.7.1.2.2.1.2."
        self.snmp_oid_mac_port_3310b = "1.3.6.1.4.1.3320.152.1.1.1"
        self.snmp_oid_all_interfaces = "1.3.6.1.2.1.31.1.1.1.1."
        self.snmp_oid_onu_status = '1.3.6.1.4.1.3320.101.10.1.1.26.'
        self.snmpoid_oid_all_onu = '1.3.6.1.4.1.3320.101.9.1.1.1.'
        self.snmp_oid_onu_lastderegtime = '1.3.6.1.4.1.3320.101.11.1.1.10'

        self.session = Session(hostname=self.ip, community=community, version=self.version, use_enums=True, timeout=30)

    
    def get_number_ports(self):
        all_interfaces = self.session.walk(self.snmp_oid_all_interfaces)
        physical_ports = filter(lambda port: re.match(r'[T]?GigaEthernet\d+/\d+', port.value), all_interfaces)
        port_numbers = [int(re.search(r'\d+', port.value).group()) for port in physical_ports]
        return len(port_numbers)


    def get_onu_status(self):
        all_status_onu = self.session.walk(self.snmp_oid_onu_status)
        
        onu_status_dict = {}

        for snmp_variable in all_status_onu:
            oid_index = snmp_variable.oid.split('.')[-1]
            value = snmp_variable.value
            onu_status_dict[int(oid_index)] = value

        return onu_status_dict


    def get_active_onu(self):
        if self.technology == "EPON":
            active_onu = self.session.walk(self.snmp_oid_active_onu)
            values = [int(var.value) for var in active_onu]
            total_sum = sum(values)
            return total_sum
        if self.technology == "GPON":
            active_onu = self.session.walk(self.snmp_oid_active_onu_gpon)
            values = [int(var.value) for var in active_onu]
            total_sum = sum(values)
            return total_sum
        if self.technology == "3310B":
             all_onu_status = self.get_onu_status()
             active_onu_count = 0

             for value in all_onu_status.values():
                if value == '3':
                    active_onu_count += 1

             return active_onu_count


    def get_numbers_ports(self, port):
        port_numbers_dict = {}
        for oid_data in self.session.walk(self.snmp_oid_all_interfaces):
            port_number = int(oid_data.oid.split(".")[-1])
            port_numbers_dict[port_number] = oid_data.value
        return port_numbers_dict if port == 'All' else {port: port_numbers_dict.get(port)}
    

    def get_description_ports(self, port='All'):
        port_description_dict = {}

        if port == 'All':
            numbers_ports = self.get_numbers_ports('All')
            i = next(iter(numbers_ports))
            port_range = range(i, self.get_number_ports() + i)
        elif isinstance(port, int):
            port_range = [port]
        else:
            raise ValueError("Так має бути")

        for i in port_range:
            description_all_ports = self.session.get(self.snmp_oid_port_description + str(i)).value
            port_description = self._classify_port_description(description_all_ports)
            port_description_dict[i] = port_description

        return port_description_dict


    
    def _classify_port_description(self, description):
        if "client" in description or "tr_" in description:
            return "client"
        elif "sw-" in description or "gw-" in description or "olt-" in description:
            return description
        else:
            return None
    
    
    def get_status_ports(self):
        port_status_dict = {}
        numbers_ports = self.get_numbers_ports('All')
        i = next(iter(numbers_ports))
        for i, port in enumerate(range(i, self.get_number_ports() + i), start=i):
            status_port = self.session.get(self.snmp_oid_status_port + str(port)).value
            port_status = "up" if status_port == '1' else "down"
            port_status_dict[i] = port_status
        return port_status_dict


    def get_mac_ports(self):
        port_mac_dict = {}
        if self.technology == "EPON" or self.technology == "GPON":
            mac_all_ports = self.session.bulkwalk("1.3.6.1.2.1.17.7.1.2.2.1.2")
        elif self.technology == "3310B":
            mac_all_ports = self.session.bulkwalk(self.snmp_oid_mac_port_3310b)

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
         mac_ports = self.get_mac_ports()
         result = {port: mac for port, mac_list in mac_ports.items() for mac in core_mac_dict if mac in mac_list}
         return self.get_description_ports(next(iter(result)))
    
    def get_switches(self):
        port_descriptions = self.get_description_ports("All")
        uplink_data = self.search_uplink()

        uplink_description = list(uplink_data.values())[0] if uplink_data else None
        switch_names = [desc for desc in port_descriptions.values() if desc and ("sw-" in desc or "gw-" in desc or "sr-te" in desc or ("olt-" in desc and "knock-" not in desc)) and desc != uplink_description]

        return get_switch_ip(self.zabbix_url, self.zabbix_user, self.zabbix_password, switch_names)
    
    def count_active_user(self):
        numbers_ports = self.get_numbers_ports('All')
        i = next(iter(numbers_ports))
        status_ports = self.get_status_ports()
        description_ports = self.get_description_ports('All')

        active_user_count = 0

        for i in range(i, self.get_number_ports() + i):
            status = status_ports.get(i)
            description = description_ports.get(i)
            if status == 'up' and description is not None and description.lower() == 'client':
                active_user_count += 1

        return active_user_count + self.get_active_onu()

class Edge_Core:
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
        physical_ports = filter(lambda port: 'Port' in port.value, all_interfaces)
        port_numbers = [int(port.value.replace('Port', '')) for port in physical_ports if any(char.isdigit() for char in port.value)]
        return len(port_numbers)


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
        elif "sw-" in description or "gw-" in description or "olt-" in description:
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
        switch_names = [desc for desc in port_descriptions.values() if desc and ("sw-" in desc or "gw-" in desc or "sr-te" in desc or ("olt-" in desc and "knock-" not in desc)) and desc != uplink_description]

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
        switch_names = [desc for desc in port_descriptions.values() if desc and ("sw-" in desc or "gw-" in desc or "sr-te" in desc or ("olt-" in desc and "knock-" not in desc)) and desc != uplink_description]

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
 
class Zyxel :

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
        port_numbers = [interface.value.split("swp")[1] for interface in all_interfaces if interface.value.startswith("swp")]
        return len(port_numbers)

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
        switch_names = [desc for desc in port_descriptions.values() if desc and ("sw-" in desc or "gw-" in desc or "sr-te" in desc or ("olt-" in desc and "knock-" not in desc)) and desc != uplink_description]

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
    
def traverse_switch_hierarchy(current_ip, active_users=0):
    switch_factory = SwitchFactory()
    switch_object = switch_factory.create_switch(current_ip, core_mac_dict, zabbix_url, zabbix_user, zabbix_password)
    if switch_object is not None:
        active_user_count = switch_object.count_active_user()
        active_users += active_user_count

        lower_switch_ips = switch_object.get_switches()
        for lower_switch_ip in lower_switch_ips:
            active_users = traverse_switch_hierarchy(lower_switch_ips[lower_switch_ip], active_users)
        
    return active_users

#ip = "10.69.96.2"
community_string = "public"
version = 2
core_mac_dict = {'88:90:09:FE:C4:6D', '88:90:09:FE:C4:6E'}
zabbix_url = 'https://zabbix6.columbus.te.ua'
zabbix_user = 'yu.petrovskyi'
zabbix_password = '7N2_55c!vDg@Kc'
model_oid = "1.3.6.1.2.1.1.1.0"
filter_descriptions = ["No main power"]
exceptions = [("knock-olt-cm-iv-1.te.clb", "olt-cm-iv-1.te.clb")
              ]

while True:
    triggers = get_zabbix_triggers(zabbix_user, zabbix_password, filter_descriptions)
    #triggers = [{'new_triggers': [], 'unresolved_triggers': [{'trigger_id': '776372', 'description': 'No main power - Battery', 'host_name': 'sw-test-main-3.te.clb', 'region': 'TEO', 'last_change_datetime': datetime.datetime(2024, 1, 4, 18, 10, 11)}, {'trigger_id': '543351', 'description': 'No main power -', 'host_name': 'knock-olt-tb-st.te.clb', 'region': 'TEO', 'last_change_datetime': datetime.datetime(2024, 2, 13, 20, 38, 33)}, {'trigger_id': '755878', 'description': 'No main power, low battery -', 'host_name': 'knock-olt-tb-st.te.clb', 'region': 'TEO', 'last_change_datetime': datetime.datetime(2024, 2, 14, 2, 54, 19)}], 'resolved_triggers': [{'trigger_id': '755878', 'description': 'No main power, low battery -', 'host_name': 'knock-olt-tb-st.te.clb', 'region': 'TEO', 'last_change_datetime': datetime.datetime(2024, 2, 14, 2, 54, 19)}]}]
    print(triggers)
    if triggers is not None:
        for trigger_info in triggers:
            #робота з новими тригерами
            for trigger in trigger_info['new_triggers']:
                print(trigger['host_name'])
                if("knock-gw-" not in trigger['host_name'] or "sr-te" not in trigger['host_name']):
                    switch_ip = get_switch_ip(zabbix_url, zabbix_user, zabbix_password, [transform_host_name(trigger['host_name'], exceptions)])
                    ip = switch_ip[transform_host_name(trigger['host_name'], exceptions)]
                    print(ip)
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            session = Session(hostname=ip, community=community_string, version=version, use_enums=True, timeout=1)
                            model_value = session.get(model_oid).value

                            if "BDCOM" in model_value or "BDCOM(tm)" in model_value:
                                object = BDCOM_LOC_POW(ip, community_string, version, core_mac_dict, zabbix_url, zabbix_user, zabbix_password)
                                if object.check_power_issues(object.get_onu_dereg_time()):
                                    print(traverse_switch_hierarchy(ip))
                                    act_users = traverse_switch_hierarchy(ip)

                                    add_TD(trigger['last_change_datetime'], get_region(zabbix_user, zabbix_password, trigger['host_name']), trigger['host_name'],  f"без основного живлення// \n {act_users} акт//")

                                    #print({"time": trigger['last_change_datetime'], "switch": trigger['host_name'], "note": f"без основного живлення// \n {act_users} акт//"})
                                else:
                                    print(traverse_switch_hierarchy(ip))
                                    act_users = traverse_switch_hierarchy(ip)

                                    add_TD(trigger['last_change_datetime'], get_region(zabbix_user, zabbix_password, trigger['host_name']), trigger['host_name'],  f"без основного живлення// \n {act_users} акт// \n розреєстрованих ону в один час не виявлено")

                                    #print({"time": trigger['last_change_datetime'], "switch": trigger['host_name'], "note": f"без основного живлення// \n {act_users} акт// \n розреєстрованих ону в один час не виявлено"})
                            else:
                                print(traverse_switch_hierarchy(ip))
                            break
                        except EasySNMPTimeoutError:
                            print(f"Таймаут {ip}. Спроба {retry+1}/{max_retries}")
                            time.sleep(1)
                        except EasySNMPError as e:
                            print(f"Error EasySNMP - {ip}: {e}")
                            break
                else:
                    print("check manually: " + trigger['host_name'])
            #робота з вирішеними тригерами
            for trigger in trigger_info['resolved_triggers']:
                close_TD(trigger['last_change_datetime'], get_region(zabbix_user, zabbix_password, trigger['host_name']), trigger['host_name'])
                

    time.sleep(5)

# obj = BDCOM(ip, community_string, version, core_mac_dict, zabbix_url, zabbix_user, zabbix_password, "3310B")
# print(obj.get_active_onu())

  
   





