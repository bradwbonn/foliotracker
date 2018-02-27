#!/usr/bin/env python

from cloudant import Cloudant
from cloudant.document import Document
from cloudant.view import View
from cloudant.design_document import DesignDocument
from cloudant.adapters import Replay429Adapter
from passlib.hash import pbkdf2_sha256

class PortfolioUser:
    
    def __init__(self, client):
        self.client = client
        self.username = None
        self.db_name = None
        self.portfolios = []
        self.email = None
        self.admin = False
        self.auth_db = self.client['investauth']
        self.logged_in = False
        self.view_definitions = [
            dict(
                ddoc = "stocks",
                views = [
                    dict(
                        view = "allowned",
                        map_func = "function (doc) {var amount; if (doc.type === 'transaction') {if (doc.action === 'buy' || doc.action === 'deposit') {amount = doc.quantity;} else if (doc.action === 'sell' || doc.action === 'withdrawl') {amount = doc.quantity * -1;}emit(doc.symbol, amount);}}",
                        reduce_func = "_sum"
                    ),
                    dict(
                        view = "bycategory",
                        map_func = "function (doc) {if (doc.type === 'stock') {emit([doc.category,doc.symbol,doc.name,doc.buybelow,doc.comments], 1);}}",
                        reduce_func = "_count"
                    ),
                    dict(
                        view = "manage",
                        map_func = "function (doc) {if (doc.type === 'stock') {emit(doc.symbol, null);}}",
                        reduce_func = "_count"
                    ),
                    dict(
                        view = "owned",
                        map_func = "function (doc) {var amount;if (doc.type === 'transaction') {if (doc.action === 'buy') {amount = doc.quantity;} else if (doc.action === 'sell') {amount = doc.quantity * -1;}emit([doc.symbol,doc.date,doc.action,doc.price], amount);}}",
                        reduce_func = "_sum"
                    )
                ]
            ),
            dict(
                ddoc = "activefolios",
                views = [
                    dict(
                        name = "currentfolio",
                        map_func = "function (doc) {if (doc.type === 'foliocache') {emit(doc._id, null);}}",
                        reduce_func = "_count"
                    )
                ]
            ),
            dict(
                ddoc = "transactions",
                views = [
                    dict(
                        name = "history",
                        map_func = "function (doc) {if (doc.type === 'transaction') {var total = (doc.price * doc.quantity) + doc.fee;emit([doc.date,doc.symbol,doc.action,doc.quantity,doc.price,doc.fee], total);}}",
                        reduce_func = "_stats"
                    )
                ]
            )
        ]
        
    def login(self, username, password):
        try:
            self.userdoc = Document(self.auth_db, username)
            self.userdoc.fetch()
            if self.check_credentials(password):
                self.username = username
                self.db_name = "investfolio-{0}".format(self.username)
                self.email = self.userdoc['email']
                self.admin = self.userdoc['admin']
                self.portfolios = self.userdoc['portfolios']
                # one portfolio is hard-coded right now
                self.selected_portfolio = self.portfolios[0]
                self.load_db()
                self.logged_in = True
                return True
            else:
                return False
        except Exception as e:
            print(e)
            return False
        
    def logout(self):
        self.db_name = None
        self.username = None
        self.email = None
        self.admin = False
        self.portfolios = None
        self.logged_in = False
        
    def check_credentials(self, password):
        # password created with pbkdf2_sha256.hash("<password>")
        if pbkdf2_sha256.verify(password, self.userdoc['password']):
            # print_local("Good password")
            return True
        else:
            # print_local("Bad password")
            return False
        
    # Data for user & db management page
    def load_admin_console(self):
        if self.admin == True:
            # get all docs from authdb for user list
            pass
            # get list of databases
            pass
            # assemble into a combined list of users and their associated metadata and the databases
            pass
            admin_page = []
            # return the data for a user list table that can be rendered by the jinja template
            for username in userlist:
                admin_page.append([username,databases[username]])
            return admin_page
        
    # Create new user
    def create_user(self, username, password, admin, portfolios):
        if self.admin == True:
            try:
                # Create user document in auth_db
                with Document(self.auth_db, username) as doc:
                    doc['password'] = pbkdf2_sha256.hash(password)
                    doc['admin'] = admin
                    doc['portfolios'] = portfolios
                # Create user's custom database and populate views
                newdb_name = "{0}".format(username)
                newdb = self.client.create_database(newdb_name)
                self.initialize_views(newdb)
                return "User created"
            except Exception as e:
                return "Cannot create user: {0}".format(e)
        
    # Delete user
    def delete_user(self, confirmation):
        if self.admin == True:
            try:
                # Match confirmation phrase and delete user ID document, and user's associated database
                pass
            except Exception as e:
                return "Unable to delete user: {0}".format(e)
        
    def load_db(self):
        # check to see if user's database exists
        self.db = self.client[self.db_name]
        # If it does, we're good If it doesn't, create it and initialize indexes
        if not self.db.exists():
            self.db = self.client.create_database(self.db_name)
            self.initialize_views(self.db)
            
    def initialize_views(self, database):
        for ddoc_definition in self.view_definitions:
            this_ddoc = DesignDocument(database, ddoc_definition['ddoc'])
            for view_definition in ddoc_definition['views']:
                this_ddoc.add_view(
                    view_definition['name'],
                    view_definition['map_func'],
                    reduce_func = view_definition['reduce_func']
                )
            this_ddoc.save()
    