#!/usr/bin/env python

# Libraries required
from cloudant import Cloudant
from cloudant.document import Document
from cloudant.view import View
from cloudant.design_document import DesignDocument
from cloudant.adapters import Replay429Adapter
from flask import Flask, render_template, request, jsonify, session, flash, redirect
from time import sleep, strftime, time
import atexit, cf_deployment_tracker, os, json, requests, sys
from Portfolio import Portfolio
from PortfolioUser import PortfolioUser

# To-do:
# admin console, function to delete transactions, fix transaction table formatting, add transaction total value to line,
# add marker for buy triggers, beautify HTML

# Enable active "log" when testing on local machine        
def print_local(output):
    if port == 8000:
        print str(output)

# On Bluemix, get the port number from the environment variable PORT
# When running this app on the local machine, default the port to 8000
port = int(os.getenv('PORT', 8000))

# Emit Bluemix deployment event
cf_deployment_tracker.track()

app = Flask(__name__)

# Cloudant client instance
client = None

# Main URL
if port == 8000:
    main_url = 'http://localhost:8000'
else:
    main_url = 'http://foliotracker.mybluemix.net'

# Connect to Cloudant
if 'VCAP_SERVICES' in os.environ:
    vcap = json.loads(os.getenv('VCAP_SERVICES'))
    print_local('Found VCAP_SERVICES')
    if 'cloudantNoSQLDB' in vcap:
        creds = vcap['cloudantNoSQLDB'][0]['credentials']
        user = creds['username']
        password = creds['password']
        url = 'https://' + creds['host']
        try:
            client = Cloudant(
                user,
                password,
                url=url,
                connect=True,
                adapter=Replay429Adapter(retries=10, initialBackoff=0.005)
            )
        except Exception as e:
            print "Unable to connect to Cloudant: {0}".format(e)
            sys.exit()
elif os.path.isfile('vcap-local.json'):
    with open('vcap-local.json') as f:
        vcap = json.load(f)
        print_local('Found local VCAP_SERVICES')
        creds = vcap['services']['cloudantNoSQLDB'][0]['credentials']
        user = creds['username']
        password = creds['password']
        url = 'https://' + creds['host']
        try:
            client = Cloudant(user,
                password,
                url=url,
                connect=True,
                adapter=Replay429Adapter(retries=10, initialBackoff=0.001)
            )
        except Exception as e:
            print "Unable to connect to Cloudant: {0}".format(e)
            sys.exit()
else:
    print('ERROR: No Cloudant connection information available!')
    sys.exit()

currentUser = PortfolioUser(client)
currentPortfolio = Portfolio(str(os.getenv('STOCKAPI')))

# Login form submission
@app.route('/login', methods=['POST','GET'])
def do_login():
    if (request.method == 'GET'):
        return render_template('login.html')
    else:
        form_user = str(request.form['username'])
        form_pass = str(request.form['password'])
        if currentUser.login(form_user,form_pass):
            session['logged_in'] = True
            currentPortfolio.load(currentUser.db, currentUser.selected_portfolio)
            print_local('Logged in!')
        else:
            print_local('Invalid login')
            flash('Invalid login!')            
        return redirect(main_url)

# Logout session
@app.route("/logout")
def logout():
    session['logged_in'] = False
    currentUser.logout()
    currentPortfolio.clear()
    return do_login()

# Admin console - TO DO
@app.route("/admin", methods=['GET'])
def admin_console():
    # If user is logged in, and an admin
    if (currentUser.admin == True):
        return("Unfinished")
        # Get user list from docs in authdb
        
        # print header and operation buttons: Add, Delete, Edit
        pass
        # print table with user info and checkbox
        pass
        
    # else, redirect to login
    else:
        return do_login()

# Add new portfolio stock
@app.route("/newstock", methods=['GET','POST'])
def newstock():
    if not (session['logged_in'] and currentUser.logged_in):
        return redirect(main_url + '/login')
    if request.method == 'GET':
        return render_template(
            'stock.html',
            subcategories = currentPortfolio.get_subcategory_list()
        )
    else:
        if request.form['active'] == 'true':
            active = True
        else:
            active = False
        currentPortfolio.new_stock(
            str(request.form['category']),
            str(request.form['symbol']),
            str(request.form['name']),
            float(request.form['buybelow']),
            str(request.form['comments']),
            active
        )
        return redirect(main_url)

# Query index to get the stock's details
@app.route("/updatestock", methods=['POST','GET'])
def update_stock():
    if (currentUser.logged_in):
        if (request.method == 'GET'):
            return render_template('updatestock.html', stock=currentPortfolio.get_stock(request.args.get('symbol')))
        else:
            currentPortfolio.update_stock(
                request.args.get('symbol'),
                request.form['name'],
                request.form['buybelow'],
                request.form['comments'],
                request.form['active']
            )
            return redirect(main_url)
    else:
        return redirect(main_url + "/login")

@app.route("/refresh", methods=['GET'])
def refresh_holdings():
    if currentUser.logged_in:
        currentPortfolio.refresh_holdings()
        return redirect(main_url)
    else:
        return redirect(main_url)

@app.route("/adduser", methods=['POST','GET'])
def add_user():
    # If session user is logged in, and an admin
    if (session['logged_in'] == True and currentUser.admin == True):
        return ("Unfinished")
    # else, go away
    else:
        return ("UNAUTHORIZED")

@app.route("/transactions", methods=['GET'])
def list_transactions():
    if session.get('logged_in') and currentUser.logged_in:
        page = int(request.args.get('page'))
        pagesize = int(request.args.get('pagesize'))
        transaction_list = currentPortfolio.get_transactions(page, pagesize)
        
        # If it's a full page, assume there's another page to go and make the button
        if len(transaction_list) == 10:
            nextpage = "{0}&pagesize={1}".format(
                page + 1,
                pagesize
            )
        else:
            nextpage = ""
        # If we're more than one page in, make the previous page button
        if page > 0:
            previouspage = "{0}&pagesize={1}".format(
                page - 1,
                pagesize
            )
        else:
            previouspage = ""
        
        # print transaction_list
        
        return render_template(
            'transactions2.html',
            transactions = transaction_list,
            prev = previouspage,
            next = nextpage,
            portfolioname = currentPortfolio.name
        )
    else:
        return redirect(main_url)

# HTML tester
@app.route("/test", methods=['GET'])
def test():
    return render_template('test.html')

# Execute trade
@app.route("/trade", methods=['POST','GET'])
def transaction():
    if currentUser.logged_in:
        if (request.method == 'GET'):
            return render_template('trade.html', message = '')
        else:
            message = currentPortfolio.trade(
                str(request.form['symbol']),
                float(request.form['quantity']),
                float(request.form['price']),
                float(request.form['fee']),
                str(request.form['action']),
                bool(int(request.form['usebalance']))
            )
            if message <> None:
                return render_template('trade.html', message = "Error: {0}".format(message))
        return redirect(main_url)
    else:
        return redirect(main_url + "/login")

# If session is not logged in, present login screen, otherwise load portfolio summary screen.
@app.route('/')
def home():
    if not currentUser.logged_in:
        print_local('user not logged in')
        return do_login()

    else:
        # Return the jinja template for the most recent cached portfolio doc
        return render_template(
            'folio2.html',
            portfolioname = currentPortfolio.name,
            portfoliodata = currentPortfolio.get_template_data(),
            portfoliovalue = "{0:,.2f}".format(currentPortfolio.total_portfolio_value),
            foliostatus = currentPortfolio.status,
            foliouser = currentUser.username
        )

# Flask runtime execution and shutdown functions    
@atexit.register
def shutdown():
    if client:
        client.disconnect()

if __name__ == '__main__':
    app.secret_key = 'algareajb342942804joefijoasdofa8d9f7ashgbu4iakwjalfdasdf234ubyito8gh9siuefjkbkdfbaydf89p8buosidnjf'
    app.config['SESSION_TYPE'] = 'cloudant'
    app.run(host='0.0.0.0', port=port, debug=True)
