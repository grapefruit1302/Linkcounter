from easysnmp import Session

class Dlink:
    def __init__(self, ip_address, community, version, core_mac_address):
        self.ip = ip_address
        self.community_string = community
        self.version = version
        self.core_mac_address=core_mac_address

        self.snmp_oid_status_port = "1.3.6.1.2.1.31.1.1.1.1."
        self.snmp_oid_all_interfaces = "1.3.6.1.2.1.2.2.1.8."
        self.snmp_oid_port_description = "1.3.6.1.2.1.31.1.1.1.18."
        self.snmp_oid_mac_port = "1.3.6.1.2.1.17.7.1.2.2.1.2.111"  


        self.session = Session(hostname=self.ip, community=community_string, version=self.version)

    def get_number_ports(self): #повертає ціле числове значення - к-ть портів 
        all_interfaces = self.session.walk(self.snmp_oid_status_port)
        last_port_number = None

        for port in all_interfaces: 
            if '/' in port.value and port.value.count('/') == 1:
                current_port_number = int(port.value.split('/')[1])
                if last_port_number is None or current_port_number > last_port_number:
                    last_port_number = current_port_number
        
        return last_port_number
    



    def get_status_ports(self): #повертає інформацію про стан портів ('up' або 'down')
        port_status_dict = {}
        number_ports = self.get_number_ports()

        for i in range(number_ports+1):
            status_port = self.session.get(self.snmp_oid_all_interfaces + str(i)).value
            port_status = "up" if status_port == '1' else "down"
            port_status_dict[i] = port_status

        return port_status_dict
    

    def get_description_ports(self, port): #повертає інформацію про підписи на портах
        port_description_dict = {}
        number_ports = self.get_number_ports()

        for i in range(number_ports+1):
            description_all_ports = self.session.get(self.snmp_oid_port_description + str(i)).value
            
            if "client" in description_all_ports:
                port_description = "client"
            elif "sw-" in description_all_ports or "gw-" in description_all_ports or "sr-te" in description_all_ports:
                port_description = description_all_ports
            else:
                port_description = None
            
            port_description_dict[i] = port_description
        
        if port == 'All':
            return port_description_dict
        else: return port_description_dict[port]

    

    def get_mac_ports(self): #повертає словник з маками, які приходять у management vlan
        port_mac_dict = {}
        mac_all_ports = self.session.walk(self.snmp_oid_mac_port)

        for var in mac_all_ports:
            port_number = int(var.value)
            mac_address_oid = var.oid.split('.')[-6:]  # Отримання останніх 6 елементів OID як мак-адреси

            # Форматування мак-адресів
            mac_address_list = [int(x) for x in mac_address_oid]
            mac_address_str = ':'.join(['{:02X}'.format(x) for x in mac_address_list])

            # Додавання до словника
            if port_number not in port_mac_dict:
                port_mac_dict[port_number] = []

            port_mac_dict[port_number].append(mac_address_str)

        return port_mac_dict
    
    def search_uplink(self): #повертає словник з номером порта та підписом
        uplink_port_data = {}
        mac_ports = self.get_mac_ports()

        for port, mac_list in mac_ports.items():
            if self.core_mac_address in mac_list:
                uplink_port_data[port] = self.get_description_ports(port)
                return uplink_port_data

        return None
    
    def count_active_user(self): #повертає к-ть активних клієнтів на світчі
        number_ports = self.get_number_ports()
        status_ports = self.get_status_ports()
        description_ports = self.get_description_ports('All')

        active_user_count = 0

        for port in range(number_ports):
            status = status_ports.get(port)
            description = description_ports.get(port)
            # Перевірити, чи порт активний і має підпис 'client'
            if status == 'up' and description.lower() == 'client':
                active_user_count += 1

        return active_user_count
    

ip ="10.69.111.53"
community_string = "public"
version = 2
core_mac_address='88:90:09:FE:C4:6D'

switch_object = Dlink(ip, community_string, version, core_mac_address)

print(switch_object.count_active_user())
