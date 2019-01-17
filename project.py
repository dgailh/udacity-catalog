from flask import Flask, render_template, request
from flask import redirect, jsonify, url_for, flash
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Genre, Game, User
from flask import session as login_session
import random
import string

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Games Library Application"


# Connect to Database and create database session
engine = create_engine('sqlite:///games.db?check_same_thread=false')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(
        random.choice(string.ascii_uppercase + string.digits)
        for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)


# connecting to google account
@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'),
            200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)
    print answer.json()
    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']
    # ADD PROVIDER TO LOGIN SESSION
    login_session['provider'] = 'google'

    # See if a user exists, if it doesn't make a new one
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;'
    output += 'border-radius: 150px;-webkit-border-radius: 150px;'
    output += '-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output


# User functions
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    # try getting the user if not exist return None to create new one!
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except Exception:
        return None


# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session['access_token']
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    if access_token is None:
        print 'Access Token is None'
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token='
    url += '%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        response = make_response(
            json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        print "this is the status " + result['status']
        response = make_response(
            json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# JSON APIs to view Genre Information
@app.route('/genre/<int:genre_id>/game/JSON')
def genreJSON(genre_id):
    genre = session.query(Genre).filter_by(id=genre_id).one()
    games = session.query(Game).filter_by(
        genre_id=genre_id).all()
    return jsonify(Games=[i.serialize for i in games])


@app.route('/genre/<int:genre_id>/game/<int:game_id>/JSON')
def gameJSON(genre_id, game_id):
    game = session.query(Game).filter_by(id=game_id).one()
    return jsonify(Game=game.serialize)


@app.route('/genre/JSON')
def genresJSON():
    genres = session.query(Genre).all()
    return jsonify(genres=[r.serialize for r in genres])


# Show all genres
@app.route('/')
@app.route('/genre/')
def showGenres():
    genres = session.query(Genre).order_by(asc(Genre.name))
    if 'username' not in login_session:
        return render_template('publicgenres.html', genres=genres)
    else:
        return render_template('genres.html', genres=genres)


# Create a new Gnre
@app.route('/genre/new/', methods=['GET', 'POST'])
def newGenre():
    if 'username' not in login_session:
        return redirect('/login')

    if request.method == 'POST':
        newGenre = Genre(
            name=request.form['name'], user_id=login_session['user_id'])
        session.add(newGenre)
        flash('New Genre %s Successfully Created' % newGenre.name)
        session.commit()
        return redirect(url_for('showGenres'))
    else:
        return render_template('newgenre.html')


# Edit a Genre
@app.route('/genre/<int:genre_id>/edit/', methods=['GET', 'POST'])
def editGenre(genre_id):
    if 'username' not in login_session:
        return redirect('/login')

    editedGenre = session.query(
        Genre).filter_by(id=genre_id).one()

    if editedGenre.user_id != login_session['user_id']:
        wrongUser = "<script>function myFunction() {alert"
        wrongUser += "('You are not authorized to edit this genre."
        wrongUser += " Please add your own genre to edit it's info"
        wrongUser += "or contact the creator.');}"
        wrongUser += "</script><body onload='myFunction()'>"
        return wrongUser

    if request.method == 'POST':
        if request.form['name']:
            editedGenre.name = request.form['name']
            flash('Genre Successfully Edited %s' % editedGenre.name)
            return redirect(url_for('showGame', genre_id=genre_id))
    else:
        return render_template('editGenre.html', genre=editedGenre)


# Delete a Genre
@app.route('/genre/<int:genre_id>/delete/', methods=['GET', 'POST'])
def deleteGenre(genre_id):
    if 'username' not in login_session:
        return redirect('/login')

    genreToDelete = session.query(
        Genre).filter_by(id=genre_id).one()

    if genreToDelete.user_id != login_session['user_id']:
        wrongUser = "<script>function myFunction() {alert"
        wrongUser += "('You are not authorized to delete this genre."
        wrongUser += " Please add your own genre to edit it's info"
        wrongUser += "or contact the creator.');}"
        wrongUser += "</script><body onload='myFunction()'>"
        return wrongUser

    if request.method == 'POST':
        session.delete(genreToDelete)
        flash('%s Successfully Deleted' % genreToDelete.name)
        session.commit()
        return redirect(url_for('showGenres'))
    else:
        return render_template('deletegenre.html', genre=genreToDelete)


# Show a genre list of games
@app.route('/genre/<int:genre_id>/')
@app.route('/genre/<int:genre_id>/game/')
def showGame(genre_id):
    genre = session.query(Genre).filter_by(id=genre_id).one()
    games = session.query(Game).filter_by(genre_id=genre_id).all()
    creator = getUserInfo(genre.user_id)
    if ('username' not in login_session
            or creator.id != login_session['user_id']):
        return render_template(
            'publicgame.html', games=games, genre=genre, creator=creator)
    else:
        return render_template(
            'game.html', games=games, genre=genre, creator=creator)


# Create a new Game
@app.route('/genre/<int:genre_id>/game/new/', methods=['GET', 'POST'])
def newGame(genre_id):
    if 'username' not in login_session:
        return redirect('/login')

    genre = session.query(Genre).filter_by(id=genre_id).one()
    if request.method == 'POST':
        newGame = Game(
                    name=request.form['name'],
                    description=request.form['description'],
                    price=request.form['price'],
                    min_age=request.form['min_age'],
                    game_link=request.form['game_link'],
                    genre_id=genre_id,
                    user_id=login_session['user_id'])
        session.add(newGame)
        session.commit()
        flash('New Game %s Successfully Added' % (newGame.name))
        return redirect(url_for('showGame', genre_id=genre_id))
    else:
        return render_template('newgame.html', genre_id=genre_id)


# Edit a game
@app.route(
    '/genre/<int:genre_id>/game/<int:game_id>/edit', methods=['GET', 'POST'])
def editGame(genre_id, game_id):
    if 'username' not in login_session:
        return redirect('/login')

    editedGame = session.query(Game).filter_by(id=game_id).one()
    genre = session.query(Genre).filter_by(id=genre_id).one()

    if editedGame.user_id != login_session['user_id']:
        wrongUser = "<script>function myFunction() {alert"
        wrongUser += "('You are not authorized to edit this game."
        wrongUser += " Please add your own game to edit it's info"
        wrongUser += "or contact the creator.');}"
        wrongUser += "</script><body onload='myFunction()'>"
        return wrongUser

    if request.method == 'POST':
        if request.form['name']:
            editedGame.name = request.form['name']
        if request.form['description']:
            editedGame.description = request.form['description']
        if request.form['price']:
            editedGame.price = request.form['price']
        if request.form['min_age']:
            editedGame.min_age = request.form['min_age']
        if request.form['game_link']:
            editedGame.game_link = request.form['game_link']
        session.add(editedGame)
        session.commit()
        flash('Game Successfully Edited')
        return redirect(url_for('showGame', genre_id=genre_id))
    else:
        return render_template(
            'editgame.html', genre_id=genre_id,
            game_id=game_id, game=editedGame)


# Delete a Game
@app.route(
    '/genre/<int:genre_id>/game/<int:game_id>/delete', methods=['GET', 'POST'])
def deleteGame(genre_id, game_id):
    if 'username' not in login_session:
        return redirect('/login')

    genre = session.query(Genre).filter_by(id=genre_id).one()
    gameToDelete = session.query(Game).filter_by(id=game_id).one()

    if gameToDelete.user_id != login_session['user_id']:
        wrongUser = "<script>function myFunction() {alert"
        wrongUser += "('You are not authorized to delete this game."
        wrongUser += " Please contact the creator.');}"
        wrongUser += "</script><body onload='myFunction()'>"
        return wrongUser

    if request.method == 'POST':
        session.delete(gameToDelete)
        session.commit()
        flash('Game Successfully Deleted')
        return redirect(url_for('showGame', genre_id=genre_id))
    else:
        return render_template(
            'deleteGame.html', game=gameToDelete, genre_id=genre_id)


# Disconnect based on provider in case of wanting to add more providers.
@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect()
            del login_session['access_token']
            del login_session['gplus_id']
            del login_session['username']
            del login_session['email']
            del login_session['picture']
        flash("You have successfully been logged out.")
        return redirect(url_for('showGenres'))
    else:
        flash("You were not logged in")
        return redirect(url_for('showGenres'))


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
