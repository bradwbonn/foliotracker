#!/usr/bin/env python

import requests,json,pprint

url = None
user = None
password = None
my_header = {'Content-Type': 'application/json'}

with open('vcap-local.json') as f:
    vcap = json.load(f)
    print('Found local VCAP_SERVICES')
    creds = vcap['services']['cloudantNoSQLDB'][0]['credentials']
    user = creds['username']
    password = creds['password']
    url = 'https://' + creds['host']

db = 'investfolio-bradbonn'

view_url = "{0}/{1}/_design/{2}/_view/{3}".format(
    url,
    db,
    'stocks',
    'bycategory'
)

view_parameters = {
    "startkey": '["{0}",{1},{2},{3},{4}]'.format("Real Estate Investment Trusts",'null','null','null','null'),
    "endkey": '["{0}",{1},{2},{3},{4}]'.format("Real Estate Investment Trusts",'{}','{}','{}','{}'),
    "reduce": 'false'
}

r = requests.get(
    view_url,
    auth = (user,password),
    headers = my_header,
    params = view_parameters
)

jsondata = r.json()

pprint.pprint(jsondata)