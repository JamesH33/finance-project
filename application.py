import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    # Store user & stock info in variables
    user = db.execute("SELECT * FROM users WHERE id = :user_id", user_id=session["user_id"])
    user = user[0]
    holdings = db.execute("SELECT * FROM stocks WHERE user_id = :user_id ORDER BY amount DESC", user_id=user["id"])

    # Initialize empty list to store lists containing each stock's info
    stocks = []

    # Initialize the grand total to the user's cash
    grand_total = user["cash"]

    # Iterate over each stock the user owns
    for row in range(len(holdings)):
        # Look up the current stock to get price info
        stock_info = lookup(holdings[row]["symbol"])

        # Create a new list of the stock's info and append to the final list
        next_stock = [holdings[row]["symbol"], stock_info["name"], holdings[row]["amount"],
                      usd(stock_info["price"]), usd(stock_info["price"] * holdings[row]["amount"])]
        stocks.append(next_stock)

        # Add the current value of the user's shares to the grand total
        grand_total += stock_info["price"] * holdings[row]["amount"]

    # Convert the total value of holdings + cash to USD format
    grand_total = usd(grand_total)

    # Render the dashboard page
    return render_template("index.html", cash=usd(user["cash"]), stocks=stocks, grand_total=grand_total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "POST":
        # Verifies that both stock symbol and number of shares are entered
        if not request.form.get("symbol") or not request.form.get("shares"):
            return apology("must specify stock symbol and number of shares", 404)

        # Lookup stock info, return error if stock isn't found
        stock = lookup(request.form.get("symbol"))
        if stock == None:
            return apology("symbol not found", 404)

        shares = request.form.get("shares")

        # Return error if shares is not positive
        if float(shares) <= 0:
            return apology("must specify positive number of shares")

        # Store current user data in local variable
        user = db.execute("SELECT * FROM users WHERE id = :user_id", user_id=session["user_id"])
        user = user[0]

        # Check if user has enough cash to buy requested shares
        total_price = float(shares) * stock["price"]
        current_cash = user["cash"]

        if current_cash > total_price:
            # Record history of purchase
            db.execute("""INSERT INTO history (user_id, symbol, amount, timestamp, price_per, total_price, transaction_type)
                       VALUES (:user_id, :symbol, :amount, datetime('now'), :price_per, :total_price, :transaction)""",
                       user_id=user["id"], symbol=stock["symbol"], amount=shares, price_per=stock["price"], total_price=total_price, transaction="Purchase")

            # Store info about user's shares of this stock in a variable
            holdings = db.execute("SELECT * FROM stocks WHERE user_id = :user_id AND symbol = :symbol",
                                  user_id=user["id"], symbol=stock["symbol"])

            # If user doesn't have any stock yet, insert a new row and update cash
            if not holdings:
                db.execute("INSERT INTO stocks (user_id, symbol, amount, timestamp) VALUES (:user, :symbol, :amount, datetime('now'))",
                           user=user["id"], symbol=stock["symbol"], amount=shares)
                db.execute("UPDATE users SET cash = :new_cash WHERE username = :username",
                           new_cash=current_cash-total_price, username=user["username"])

            # If user does have stock, update the amount and their cash
            else:
                holdings = holdings[0]
                current_amount = holdings["amount"]
                db.execute("UPDATE stocks SET amount = :new_amount WHERE user_id = :user_id",
                           new_amount=current_amount + int(shares), user_id=user["id"])
                db.execute("UPDATE users SET cash = :new_cash WHERE username = :username",
                           new_cash=current_cash-total_price, username=user["username"])
            return redirect("/")
        else:
            return apology("not enough cash to buy requested shares")
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    # Retrieve user's transactions
    transactions = db.execute("SELECT * FROM history WHERE user_id = :user_id ORDER BY timestamp DESC", user_id=session["user_id"])
    for row in transactions:
        row["price_per"] = usd(row["price_per"])
        row["total_price"] = usd(row["total_price"])
    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():

    if request.method == "POST":
        # Check that symbol is found:
        if not request.form.get("symbol"):
            return apology("must specify stock symbol", 404)

        # Store quote info in a variable, display error if not found
        quote = lookup(request.form.get("symbol"))

        if quote == None:
            return apology("symbol not found", 404)

        # Render the template, sending the quote to the HTML
        return render_template("quoted.html", quote=quote)

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Validating that all fields are complete and that password confirmation matches
        if not request.form.get("username"):
            return apology("must provide username")
        elif not request.form.get("password"):
            return apology("must provide password")
        elif not request.form.get("confirmation"):
            return apology("must confirm password")
        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords do not match")

        # Store username and password hash as variables to insert into database
        username = request.form.get("username")
        pw_hash = generate_password_hash(request.form.get("password"), method='pbkdf2:sha256', salt_length=8)

        # Check if username already exists
        uncheck = db.execute("SELECT username FROM users WHERE username = :username", username=username)

        if not uncheck:
            # Insert new user into database, then redirect to index
            db.execute("INSERT INTO users (username, hash) VALUES (:username, :pw_hash)", username=username, pw_hash=pw_hash)
            return redirect("/")
        else:
            # Show apology if username already exists
            return apology("username already exists")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    # Store user and stock data in local variables
    user = db.execute("SELECT * FROM users WHERE id = :user_id", user_id=session["user_id"])
    user = user[0]

    # Function for attempting a sale
    if request.method == "POST":
        # Verifies that both stock symbol and number of shares are entered
        if not request.form.get("symbol") or not request.form.get("shares"):
            return apology("must specify stock symbol and number of shares", 404)

        stock = lookup(request.form.get("symbol"))
        shares = int(request.form.get("shares"))

        # Return error if shares is not positive
        if float(shares) <= 0:
            return apology("must specify positive number of shares")

        # Store info about user's holdings in a variable
        holdings = db.execute("SELECT * FROM stocks WHERE user_id = :user_id AND symbol = :symbol",
                              user_id=user["id"], symbol=stock["symbol"])
        holdings = holdings[0]

        # Return error if they are trying to sell more than they have
        if shares > holdings["amount"]:
            return apology("trying to sell more shares than you own")

        price = stock["price"] * shares
        new_cash = user["cash"] + price
        new_amount = holdings["amount"] - shares

        # Record sale in history
        db.execute("""INSERT INTO history (user_id, symbol, amount, timestamp, price_per, total_price, transaction_type)
                   VALUES (:user_id, :symbol, :amount, datetime('now'), :price_per, :total_price, 'Sale')""",
                   user_id=user["id"], symbol=stock["symbol"], amount=shares, price_per=stock["price"], total_price=price)

        # Delete row from stocks table if user sells all of their shares
        if new_amount == 0:
            db.execute("DELETE FROM stocks WHERE user_id = :user_id AND symbol = :symbol",
                       user_id=user["id"], symbol=stock["symbol"])

        # Update the amount of shares if the user still has some
        else:
            db.execute("UPDATE stocks SET amount = :new_amount WHERE user_id = :user_id AND symbol = :symbol",
                       new_amount=new_amount, user_id=user["id"], symbol=stock["symbol"])

        db.execute("UPDATE users SET cash = :new_cash WHERE id = :user_id", new_cash=new_cash, user_id=user["id"])

        return redirect("/")
    # Function for visiting the sell page
    else:
        holdings = db.execute("SELECT * FROM stocks WHERE user_id = :user_id", user_id=user["id"])
        return render_template("sell.html", holdings=holdings)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
