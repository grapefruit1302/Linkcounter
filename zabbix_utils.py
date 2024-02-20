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
                #print(self.previous_triggers)
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
    
    def get_node_by_host(self, host_name):
        auth_token = self.login()
        host_id = None

        if auth_token:
            get_hosts_data = {
                "jsonrpc": "2.0",
                "method": "host.get",
                "params": {
                    "output": ["hostid"],
                    "filter": {"host": host_name}
                },
                "auth": auth_token,
                "id": 1,
            }

            response = requests.post(self.api_url, json=get_hosts_data)
            hosts_result = response.json()

            if 'result' in hosts_result:
                host_id = hosts_result['result'][0]['hostid']

        if host_id:
            group_payload = {
                "jsonrpc": "2.0",
                "method": "host.get",
                "params": {
                    "output": ["groups"],
                    "selectGroups": "extend",
                    "hostids": host_id
                },
                "auth": auth_token,
                "id": 1
            }
            group_response = requests.post(self.api_url, json=group_payload)
            group_result = group_response.json()

            groups = []
            if group_result.get("result"):
                groups = group_result["result"][0]["groups"]
            node = None

            for group in groups:
                if "[Network]/Тернопіль/Columbus" in group["name"]:
                    node = "TE"
                    break
                elif "[Network]/Тернопіль/Bitternet" in group["name"]:
                    node = "TEO"
                    break
                elif "[Network]/Червоноград/Володимир" in group["name"] and "-vv-" in host_name:
                    node = "VV"
                    break
                elif "-cg-" in host_name:
                    node = "CG"
                    break

            return node

        return "Not found"

                

    def get_current_triggers(self, filter_description):
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
            trigger_data_list = []
            current_triggers = set()

            for trigger in trigger_result['result']:
                trigger_id = trigger['triggerid']
                current_triggers.add(trigger_id)

                host_name = trigger['hosts'][0]['name'] if trigger['hosts'] else 'Unknown'
                last_change = trigger['lastchange']
                last_change_datetime = datetime.datetime.fromtimestamp(int(last_change))

                trigger_data = {
                    'trigger_id': trigger_id,
                    'description': trigger['description'],
                    'host_name': host_name,
                    'region': self.get_node_by_host(host_name),
                    'last_change_datetime': last_change_datetime
                }

                if("olt-cn" not in trigger_data['host_name']):
                    trigger_data_list.append(trigger_data)

            return trigger_data_list

        else:
            print("No active triggers found for the specified description.")


    def process_triggers(self, filter_description, domains):

        trigger_data_list = self.get_current_triggers(filter_description)
        trigger_info = {
        'new_triggers': [],
        'resolved_triggers': []
    }

        current_trigger_ids = {trigger['trigger_id'] for trigger in trigger_data_list}

        new_trigger_ids = current_trigger_ids - self.previous_triggers
        resolved_trigger_ids = self.previous_triggers - current_trigger_ids

        unresolved_trigger_ids = self.previous_triggers & current_trigger_ids

        for trigger in trigger_data_list:
            if trigger['trigger_id'] in unresolved_trigger_ids:
                print(f"{trigger['trigger_id']} - {trigger['host_name']}")

        for trigger in trigger_data_list:
            if trigger['trigger_id'] in new_trigger_ids and (trigger['host_name'].endswith('.te.clb') or trigger['host_name'].endswith('.te.clb_2')):
                trigger_info['new_triggers'].append(trigger)


        for trigger_id in resolved_trigger_ids:
            trigger_info['resolved_triggers'].append(trigger)

        self.previous_triggers = current_trigger_ids
        self.save_previous_triggers()

        return trigger_info

    def logout(self):
        logout_data = {
            "jsonrpc": "2.0",
            "method": "user.logout",
            "params": [],
            "auth": self.auth_token,
            "id": 3,
        }

        requests.post(self.api_url, json=logout_data)


def get_zabbix_triggers(username, password, filter_descriptions, domains):
    api_url = 'https://zabbix6.columbus.te.ua/api_jsonrpc.php'
    zabbix_api = MyZabbixAPI(api_url, username, password)
    zabbix_api.login()
    
    all_trigger_info = []
    for filter_description in filter_descriptions:
        trigger_info = zabbix_api.process_triggers(filter_description, domains)
        all_trigger_info.append(trigger_info)
        
    zabbix_api.logout()
    
    return all_trigger_info


def get_region(username, password, host):
    api_url = 'https://zabbix6.columbus.te.ua/api_jsonrpc.php'
    zabbix_api = MyZabbixAPI(api_url, username, password)
    zabbix_api.login()
    
    return zabbix_api.get_node_by_host(host)


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





