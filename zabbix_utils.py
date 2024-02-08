from pyzabbix import ZabbixAPI
import requests
import json
import time
import datetime
import re

class MyZabbixAPI:
    def __init__(self, api_url, username, password):
        self.api_url = api_url
        self.username = username
        self.password = password
        self.auth_token = None
        self.previous_triggers = set()
        self.load_previous_triggers()

    def login(self):
        login_data = {
            "jsonrpc": "2.0",
            "method": "user.login",
            "params": {
                "user": self.username,
                "password": self.password,
            },
            "id": 1,
        }

        response = requests.post(self.api_url, json=login_data)
        auth_result = response.json()
        self.auth_token = auth_result.get('result')

        return self.auth_token

    def load_previous_triggers(self):
        try:
            with open("previous_triggers.json", "r") as file:
                self.previous_triggers = set(json.load(file))
        except FileNotFoundError:
            pass

    def save_previous_triggers(self):
        with open("previous_triggers.json", "w") as file:
            json.dump(list(self.previous_triggers), file)

    def comment_trigger(self, trigger_id, comment):
        headers = {'Content-Type': 'application/json-rpc'}
        payload = {
            "jsonrpc": "2.0",
            "method": "trigger.update",
            "params": {
                "triggerid": trigger_id,
                "comments": comment
            },
            "auth": self.auth_token,
            "id": 1,
        }
        response = requests.post(self.api_url, headers=headers, data=json.dumps(payload))
        result = response.json()
        return result
        

    def get_active_triggers(self, filter_description):
        trigger_data_list = []
        current_triggers = set()

        get_triggers_data = {
            "jsonrpc": "2.0",
            "method": "trigger.get",
            "params": {
                "output": ["triggerid", "description", "lastchange"],
                "selectHosts": ["name", "hostid"],
                "search": {"description": filter_description},
                "expandData": 1,
                "filter": {"value": 1}
            },
            "auth": self.auth_token,
            "id": 2,
        }

        response = requests.post(self.api_url, json=get_triggers_data)
        trigger_result = response.json()

        if 'result' in trigger_result:
            print("Current time: " + str(datetime.datetime.now()))

            for trigger in trigger_result['result']:
                trigger_id = trigger['triggerid']
                current_triggers.add(trigger_id)

                host_name = trigger['hosts'][0]['name'] if trigger['hosts'] else 'Unknown'
                host_id = trigger['hosts'][0]['hostid'] if trigger['hosts'] else None
                last_change = trigger['lastchange']
                last_change_datetime = datetime.datetime.fromtimestamp(int(last_change))

                # Отримання назви панелі
                panel_name = self.get_host_panel_name(host_id)

                trigger_data = {
                    'trigger_id': trigger_id,
                    'description': trigger['description'],
                    'host_name': host_name,
                    'panel_name': panel_name,
                    'last_change_datetime': last_change_datetime
                }

                trigger_data_list.append(trigger_data)

            new_triggers = current_triggers - self.previous_triggers
            unresolved_triggers = self.previous_triggers & current_triggers
            resolved_triggers = self.previous_triggers - current_triggers

            trigger_info = {
                'new_triggers': [],
                'unresolved_triggers': [],
                'resolved_triggers': []
            }

            for trigger in trigger_data_list:
                if trigger['trigger_id'] in new_triggers and (trigger['host_name'].endswith('.te.clb') or trigger['host_name'].endswith('.te.clb_2')):
                    trigger_info['new_triggers'].append(trigger)

            for trigger in trigger_data_list:
                if trigger['trigger_id'] in unresolved_triggers and (trigger['host_name'].endswith('.te.clb') or trigger['host_name'].endswith('.te.clb_2')):
                    trigger_info['unresolved_triggers'].append(trigger)

            for trigger_id in resolved_triggers:
                trigger_info['resolved_triggers'].append(trigger_id)

            self.previous_triggers = current_triggers
            self.save_previous_triggers()

            return trigger_info

        else:
            print("No active triggers found for the specified description.")

    def get_host_panel_name(self, host_id):
        get_host_data = {
            "jsonrpc": "2.0",
            "method": "host.get",
            "params": {
                "output": ["hostid", "name"],
                "selectGroups": ["name"],
                "hostids": [host_id]
            },
            "auth": self.auth_token,
            "id": 4,
        }

        response = requests.post(self.api_url, json=get_host_data)
        host_result = response.json()

        if 'result' in host_result:
            host = host_result['result'][0]
            # Перевірка наявності панелі
            if 'groups' in host and host['groups']:
                for group in host['groups']:
            
                    return group['name']
        return None

    def logout(self):
        logout_data = {
            "jsonrpc": "2.0",
            "method": "user.logout",
            "params": [],
            "auth": self.auth_token,
            "id": 3,
        }

        requests.post(self.api_url, json=logout_data)


def get_zabbix_triggers(username, password, filter_descriptions):
    api_url = 'https://zabbix6.columbus.te.ua/api_jsonrpc.php'
    zabbix_api = MyZabbixAPI(api_url, username, password)
    zabbix_api.login()
    
    all_trigger_info = []
    for filter_description in filter_descriptions:
        trigger_info = zabbix_api.get_active_triggers(filter_description)
        all_trigger_info.append(trigger_info)
        
    zabbix_api.logout()
    
    return all_trigger_info



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




def transform_host_name(host_name, exceptions):
    for exception in exceptions:
        if host_name == exception[0]:
            return exception[1]
    parts = host_name.split('.')
    if len(parts) == 3 and parts[-1] == 'clb':
        if 'knock-' in parts[0] and 'olt' in parts[0] and '-1' in parts[0]:
            new_host_name = parts[0].replace('knock-', '') + '.te.clb'
        else:
            prefix = parts[0].replace('knock-', '')
            if 'knock-' in parts[0]:
                if prefix.startswith('-'):
                    new_host_name = prefix + '1.te.clb'
                else:
                    new_host_name = prefix + '-1.te.clb'
            else:
                new_host_name = host_name
        return new_host_name
    else:
        return host_name


    

# if __name__ == "__main__":
#     api_url = ''
#     username = ''
#     password = ''
#     zabbix = MyZabbixAPI(api_url, username, password)
#     zabbix.login()
#     trigger_id = '11'
#     comment_text = "Тестовий коментар"

#     result = zabbix.comment_trigger(trigger_id, comment_text)

#         # Перевірка результату
#     if 'result' in result:
#         print("Тригер успішно коментований.")
#     else:
#         print("Помилка: ", result['error']['data'])
