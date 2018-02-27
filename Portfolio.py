#!/usr/bin/env python

# BUGS:
# - New transaction "deposit" causes duplicate entry in DB
# - Selecting "No" still causes trades to be executed against cash balanace

from cloudant import Cloudant
from cloudant.document import Document
from cloudant.view import View
from cloudant.design_document import DesignDocument
from cloudant.adapters import Replay429Adapter
from time import time, strftime
import requests, json

class Portfolio:
    def __init__(self, stockAPIkey):
        print("Portfolio.init()")
        self.stocks = dict() # Contains all stocks, both owned and tracked, with all their metadata
            # { symbol: {metadata} }
        self.categories = dict() # Contains major categories with arrays of (sub)categories and their metadata
            # { category: { target: %, actual: %, type: 'stock/fixed income' }}
        self.prices_last_updated = None # Might use this to update prices on a schedule
        self.foliodoc = None # placeholder for Cloudant document that stores portfolio metadata
        self.stockAPIkey = stockAPIkey
        self.total_portfolio_value = 0
        
    def load(self, db, portfolioname):
        print("Portfolio.load()")
        # Initialize database and variables
        self.name = portfolioname
        self.db = db
        
        # Initialize Cloudant database views
        self.stockddoc = DesignDocument(self.db, 'stocks')
        self.stockddoc.fetch()
        self.bycategory_view = self.stockddoc.get_view('bycategory')
        self.owned_view = self.stockddoc.get_view('owned')
        self.allowned_view = self.stockddoc.get_view('allowned')
        self.folio_ddoc = DesignDocument(self.db, 'activefolios')
        self.folio_ddoc.fetch()
        self.active_folios_view = self.folio_ddoc.get_view('currentfolio')
        
        self.populate_categories()
        
        self.populate_stocks()
        
        self.refresh_total_value()
        
    # Load available category metadata into memory from DB
    # *** BROKEN ***  Populating incorrect data
    def populate_categories(self):
        pass
        print("Portfolio.populate_categories()")
        # Load portfolio specification document from DB
        self.foliodoc = Document(self.db, self.name)
        self.foliodoc.fetch()
        # print("Foliodoc data: (categories field) {0}".format(self.foliodoc['categories']))
        for category in self.foliodoc['categories']:
            # print category
            for subcategory in self.foliodoc['categories'][category].keys():
                # print "Subcategory name: {0} Target: {1}".format(subcategory, self.foliodoc['categories'][category][subcategory])
                self.categories[subcategory] = dict(
                    target = self.foliodoc['categories'][category][subcategory],
                    actual = 0,
                    type = category
                )
        # print("...loaded: {0}".format(self.categories))
        
    # Populate stock metadata in memory from DB. (tracked and owned)
    def populate_stocks(self):
        print("Portfolio.populate_stocks()")
        
        # get metadata on stocks we're tracking in the portfolio
        with self.bycategory_view.custom_result(
            include_docs = True,
            reduce = False
        ) as rslt:
            for line in rslt:
                doc = line['doc']
                if doc['symbol'] == 'Cash':
                    temp_price = 1
                else:
                    temp_price = -1
                self.stocks[doc['symbol']] = dict(
                    symbol = doc['symbol'],
                    name = doc['name'],
                    comments = doc['comments'],
                    active = doc['active'],
                    buybelow = doc['buybelow'],
                    lastprice = temp_price,
                    category = doc['category'],
                    qty = 0
                )
        
    # Refresh current total value of portfolio for percentage calcuations and update subcategory totals        
    def refresh_total_value(self):
        print("Portfolio.refresh_total_value()")
        self.total_portfolio_value = 0
        # Make sure prices are current
        quote_success = False
        while quote_success <> True:
            quote_success = self.refresh_all_stock_prices()
        
        # Update quantities of stocks we own
        with self.allowned_view.custom_result(
            reduce = True,
            include_docs = False,
            group_level = 1
            ) as resultcollection:
                for stock in resultcollection:
                    self.stocks[stock['key']]['qty'] = stock['value']
        
        # total up the account's value
        for stock in self.stocks.values():
            self.total_portfolio_value = self.total_portfolio_value + (stock['qty'] * stock['lastprice'])
            
        # Update each subcategory's percentage by summing the stocks within it
        # Right now this is a nested for loop, but through data in memory.
        category_value = 0
        for category_name in self.categories.keys():
            for stock in self.stocks.values():
                if stock['category'] == category_name:
                    category_value = category_value + stock['lastprice'] * stock['qty']
            self.categories[category_name]['actual'] = (category_value / self.total_portfolio_value) * 100
            category_value = 0
        
        
    def get_subcategory_list(self):
        print("Portfolio.get_subcategory_list()")
        return self.categories.keys()
        
    def refresh_all_stock_prices(self):
        print("Portfolio.refresh_all_stock_prices()")
            
        # construct string for API call
        symbols_string = ''
        for symbol in self.stocks.keys():
            if symbol <> "Cash":
                symbols_string = symbols_string + "{0},".format(symbol)
            
        # trim last comma
        symbols_string = symbols_string[:-1]
        
        # execute stock API call
        start_time = time()
        myurl = "https://www.alphavantage.co/query?function=BATCH_STOCK_QUOTES&symbols={0}&apikey={1}".format(
            symbols_string,
            self.stockAPIkey
        )
        try:
            r = requests.get(
                url = myurl
            )
            data = r.json()
            end_time = time()
            for stock_data in data['Stock Quotes']:
                # set the price of the holding in question 
                self.stocks[stock_data['1. symbol']]['lastprice'] = float(stock_data['2. price'])
            print("Stock API query time: {0} seconds".format(float(end_time - start_time)))
            self.prices_last_updated = int(time())
            return True
        except Exception as e:
            print("Unable to get stock prices: {0}".format(e))
            return False
    
    # Create a new doc to track this stock and add it to the dictionary of stock data
    # custom ID is OK, since it prevents duplicate stock trackers
    # We should keep all prices in memory exclusively, or create "quote" docs
    # This DOES NOT store information about how much we own, because that's event sourced by transactions
    def new_stock(self, category, symbol, name, buybelow, comments, active):
        print("Portfolio.new_stock()")
        with Document(self.db, symbol) as stockdoc:
            stockdoc['type'] = 'stock'
            stockdoc['updated'] = strftime("%Y-%m-%d %H:%M:%S")
            stockdoc['category'] = category
            stockdoc['symbol'] = symbol
            stockdoc['active'] = active
            stockdoc['name'] = name
            stockdoc['comments'] = comments
            stockdoc['buybelow'] = buybelow
            self.stocks[symbol] = json.loads(stockdoc.json())
        # Get a quote for the new stock
        self.stocks[symbol]['lastprice'] = -1
        self.stocks[symbol]['qty'] = 0
        
        # update all holdings and totals
        self.refresh_total_value()
    
    def new_transaction_doc(self, symbol, quantity, price, fee, action):
        xactiondoc = Document(self.db)
        xactiondoc['type'] = 'transaction'
        xactiondoc['action'] = action
        xactiondoc['quantity'] = quantity
        xactiondoc['date'] = strftime("%Y-%m-%d %H:%M:%S")
        xactiondoc['fee'] = fee
        xactiondoc['price'] = price
        if action == 'deposit' or action == 'withdrawl':
            xactiondoc['symbol'] = 'Cash'
            xactiondoc['price'] = 1    
        else: #otherwise use symbol passed and check to see if updating cash is needed
            xactiondoc['symbol'] = symbol
        xactiondoc.save()
    
    # Execute a transaction document and update cash balance (if appropriate)
    def trade(self, symbol, quantity, price, fee, action, usebalance):
        print ("Portfolio.trade()")
        self.new_transaction_doc(symbol, quantity, price, fee, action)
        if usebalance == True:
            cashqty = (quantity * price) + fee
            if action == 'buy':
                cashaction = 'withdrawl'
            else:
                cashaction = 'deposit'
            self.new_transaction_doc('Cash',cashqty,1,0,cashaction)
        self.refresh_total_value()
 
    # Return currently cached metadata for this stock
    def get_stock(self, symbol):
        return self.stocks[symbol]
    
    # Get an individual stock symbol's quote via the API
    def get_quote(self, symbol):
        print("Portflio.get_quote({0})".format(symbol))
        myurl = "https://www.alphavantage.co/query?function=BATCH_STOCK_QUOTES&symbols={0}&apikey={1}".format(
            symbol,
            self.stockAPIkey
        )
        try:
            r = requests.get(
                url = myurl
            )
            data = r.json()
            return float(data['Stock Quotes'][0]['2. price'])
        except Exception as e:
            print_local("Unable to get stock price: {0}".format(e))
            return -1
    
    # Update a tracked stock's metadata
    def update_stock(self, symbol, name, buybelow, comments, active):
        with Document(self.db, symbol) as doc:
            doc['updated'] = strftime("%Y-%m-%d %H:%M:%S")
            doc['name'] = str(name)
            if active == 'true':
                doc['active'] = True
            else:
                doc['active'] = False
            doc['buybelow'] = int(buybelow)
            doc['comments'] = str(comments)
            
            for x in ('updated','name','active','buybelow','comments'):            
                self.stocks[symbol][x] = doc[x]

    # Neutralize content upon logout    
    def clear(self):
        print("Portfolio.clear()")
        self.name = None
        self.db = None
        self.categories = dict()
        self.stocks = dict()
        self.prices_last_updated = None
        self.total_portfolio_value = 0
        self.foliodoc = None
        
    # Return list of historical trasactions from DB
    def get_transactions(self, page, pagesize):
        print("Portfolio.get_transactions()")
        skip = page * pagesize
        ddoc = DesignDocument(self.db, 'transactions')
        ddoc.fetch()
        view = View(ddoc,'history')
        return view(include_docs=False, limit=pagesize, skip=skip, reduce=False)['rows']
    
    # Return a full state of the portfolio with metadata formatted for the Jinja template's rendering
    def get_template_data(self):
        print "Portfolio.get_template_data()"
        # returned as "portfolio_categories" in old model
        template_data = dict()
        
        # Iterate through the sub-categories
        for subcategory in self.categories.keys():
            # print "Processing {0}:\nData: {1}".format(subcategory,self.categories[subcategory])
            # local dictionary for this subcategory's data to go into the array above. Insert what we have so far
            subcategory_data = dict(
                type =  subcategory,
                target_percentage = self.categories[subcategory]['target'],
                value = 0, # Tracks total value of all invested holdings in this particular subcategory (not used right now)
                actual_percentage = "{0:,.1f}".format(self.categories[subcategory]['actual']), 
                holdings = [] # array for all stocks in this subcat
            )
            
            template_data[subcategory] = subcategory_data
            
        # print template_data
        # Iterate through all tracked stocks in this subcategory
        for stock in self.stocks.keys():
            # print("Processing {0}: Data from stocks dictionary: {1}".format(stock,self.stocks[stock]))
            # print_local("Category: {0} Stock: {1}".format(subcategory, stock['symbol']))
            # local dictionary for this stock's data
            stock_data = dict(
                symbol = self.stocks[stock]['symbol'],
                name = self.stocks[stock]['name'],
                qty = self.stocks[stock]['qty'],
                price = "$ {0:,.2f}".format(self.stocks[stock]['lastprice']),
                buy_below = "$ {0:,.2f}".format(self.stocks[stock]['buybelow']),
                comments = self.stocks[stock]['comments'],
                value = "$ {0:,.2f}".format(float(self.stocks[stock]['qty'] * self.stocks[stock]['lastprice'])) # value of this security owned
            )
            template_data[self.stocks[stock]['category']]['holdings'].append(stock_data)
        # print template_data
        return template_data
    
    # Generic event source function for either getting most recent or reduce (simple key only)
    # if reduce == True, then it returns exact reduce, else returns most recent complete doc
    #def event_source(db, ddoc_name, view_name, key, bound, reduce):
    #    ddoc = DesignDocument(db, ddoc_name)
    #    ddoc.fetch()
    #    view = ddoc.get_view(view_name)
    #    if reduce == False:
    #        with view.custom_result(
    #            reduce=False,
    #            include_docs=True,
    #            descending=True,
    #            limit=1,
    #            startkey=key + bound,
    #            endkey=key
    #        ) as result:
    #            return result[0][0]['doc']
    #    else:
    #        with view.result():
    #            return result[key: key]
    
    ## Get a list of stocks for a given subcategory from the database (legacy)
    def get_subcategory_stocks(self,subcat):
    #    print("Portfolio.get_subcategory_stocks()")
    #    stocklist = []
    #    with self.bycategory_view.custom_result(reduce=False, include_docs=False) as resultcollection:
    #        rslt = resultcollection[[subcat, None, None, None, None]: [subcat, {}, {}, {}, {}]]
    #    for line in rslt:
    #        stock_info = line['key']
    #        stock_details = dict(
    #            symbol = stock_info[1],
    #            name = stock_info[2],
    #            buy_below = stock_info[3],
    #            comments = stock_info[4]
    #        )
    #        stocklist.append(stock_details)
    #    return stocklist
        pass