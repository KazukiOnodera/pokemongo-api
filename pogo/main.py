#!/usr/bin/python
"""


"""
import argparse
import logging
import time
import sys
from custom_exceptions import GeneralPogoException

from api import PokeAuthSession
from location import Location

from pokedex import pokedex
from inventory import items
import numpy as np
from progressbar import ProgressBar

start_time = time.time()
#==============================================================================

ROUND = 300000 # (pokemon get + poke stop) * ROUND

STEP = 8.2 # 3,2==11.52km/h
SLEEP = 100 # sec
COOLDOWN = 2

#==============================================================================
# MODE select
#==============================================================================
print '=== MODE select ==='
print '1: POKESTOP MARATHON'
print '2: Catch and Pokestop'
print '3: DRATINI MARATHON'
print '4: PIDGEY MARATHON(not implemented yet)'
#print '5: ?????? MARATHON' #secret mode :)


raw = raw_input('Choose mode!(1~4) >>>')
POKESTOP_MARATHON = False
IS_RESET_LOCATION = True # If True, reset location using initial location
RESET_LOCATION_ROUND = 30
pids = None
if raw == '1':
    POKESTOP_MARATHON = True # If True, not to try to catch Pokemon
    MODE = 'POKESTOP MARATHON'
elif raw == '2':
    MODE = 'Catch and Pokestop'
elif raw == '3':
    RESET_LOCATION_ROUND = 10
    MODE = 'DRATINI MARATHON'
elif raw == '4':
    MODE = 'PIDGEY MARATHON'
elif raw == '5':
    raw = raw_input('Ok... input pokedex No.(csv)>>>')
    try:
        raw = map(int, raw.split(','))
    except:
        raise Exception('input pokedex No.')
    if all(map(lambda x:1 <= x <= 151, raw)):
        pids = raw[:]
    else:
        raise Exception('input pokedex No.')
    MODE = ' & '.join(map(lambda x:pokedex[x],pids))+' MARATHON'
    MODENO = 5
else:
    raise Exception('input (1~4)')

if MODENO==None:
    MODENO = int(raw)

raw = raw_input('RANDOM ACCESS to Pokestop??(y/n) >>>')
if raw == 'y':
    RANDOM_ACCESS = True # If True, not to try to catch Pokemon
    MODE += '(Random access)'
elif raw == 'n':
    RANDOM_ACCESS = False
    MODE += '(Closest access)'
else:
    raise Exception('input y/n')


#raw = raw_input('STEP??(if 3.2, move at 11.52km/h) >>>')
#if raw.isdigit():
#    STEP = float(raw)
#else:
#    raise Exception('input float')




#==============================================================================
# def
#==============================================================================
def setupLogger():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('Line %(lineno)d,%(filename)s - %(asctime)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)


# Example functions
# Get profile
def getProfile(session):
        logging.info("Printing Profile:")
        profile = session.getProfile()
        logging.info(profile)


# Grab the nearest pokemon details
def findBestPokemon(session, pids=None):
    # Get Map details and print pokemon
    logging.info("Finding Nearby Pokemon:")
    cells = session.getMapObjects()
    closest = float("Inf")
    best = -1
    pokemonBest = None
    latitude, longitude, _ = session.getCoordinates()
    logging.info("Current pos: %f, %f" % (latitude, longitude))
    for cell in cells.map_cells:
        # Heap in pokemon protos where we have long + lat
        pokemons = [p for p in cell.wild_pokemons] + [p for p in cell.catchable_pokemons]
        for pokemon in pokemons:
            # Normalize the ID from different protos
            pokemonId = getattr(pokemon, "pokemon_id", None)
            if not pokemonId:
                pokemonId = pokemon.pokemon_data.pokemon_id
                
            # If pids exist, only target those
            if pids!=None and not pokemonId in pids:
                pass
            else:
                # Find distance to pokemon
                dist = Location.getDistance(
                    latitude,
                    longitude,
                    pokemon.latitude,
                    pokemon.longitude
                )
    
                # Log the pokemon found
                logging.info("%s, %f meters away" % (
                    pokedex[pokemonId],
                    dist
                ))
    
                rarity = pokedex.getRarityById(pokemonId)
                # Greedy for rarest
                if rarity > best:
                    pokemonBest = pokemon
                    best = rarity
                    closest = dist
                # Greedy for closest of same rarity
                elif rarity == best and dist < closest:
                    pokemonBest = pokemon
                    closest = dist
    return pokemonBest


# Wrap both for ease
def encounterAndCatch(session, pokemon, thresholdP=0.5, limit=5, delay=2):
    # Start encounter
    session.encounterPokemon(pokemon)
    
    # Have we used a razz berry yet?
    berried = False

    # Make sure we aren't over limit
    count = 0

    # Attempt catch
    while True:
        #initialize inventory
        bag = session.checkInventory().bag
        
        # try a berry
        if not berried and items.RAZZ_BERRY in bag and bag[items.RAZZ_BERRY]:
            logging.info("Using a RAZZ_BERRY")
            session.useItemCapture(items.RAZZ_BERRY, pokemon)
            berried = True
            time.sleep(delay)
            continue
        
        # Get ball list
        balls = [items.POKE_BALL] * bag[items.POKE_BALL] + \
                [items.GREAT_BALL] * bag[items.GREAT_BALL] + \
                [items.ULTRA_BALL] * bag[items.ULTRA_BALL]

        # Choose ball with randomness
        # if no balls, there are no balls in bag
        if len(balls) == 0:
            print "Out of usable balls"
            break
        else:
            bestBall = np.random.choice(balls)

        # Try to catch it!!
        logging.info("Using a %s" % items[bestBall])
        attempt = session.catchPokemon(pokemon, bestBall)
        time.sleep(delay)

        # Success or run away
        if attempt.status == 1:
            print pokedex.AA[pokemon.pokemon_data.pokemon_id]
            return attempt

        # CATCH_FLEE is bad news
        if attempt.status == 3:
            logging.info("Possible soft ban.")
            return attempt

        # Only try up to x attempts
        count += 1
        if count >= limit:
            logging.info("Over catch limit")
            return None


# Catch a pokemon at a given point
def walkAndCatch(session, pokemon):
    if pokemon:
        logging.info("Catching %s:" % pokedex[pokemon.pokemon_data.pokemon_id])
        session.walkTo(pokemon.latitude, pokemon.longitude, step=getStep())
        logging.info(encounterAndCatch(session, pokemon))


# Do Inventory stuff
def getInventory(session):
    logging.info("Get Inventory:")
    logging.info(session.getInventory())


# Basic solution to spinning all forts.
# Since traveling salesman problem, not
# true solution. But at least you get
# those step in
def sortCloseForts(session):
    # Sort nearest forts (pokestop)
    logging.info("Sorting Nearest Forts:")
    cells = session.getMapObjects()
    latitude, longitude, _ = session.getCoordinates()
    ordered_forts = []
    for cell in cells.map_cells:
        for fort in cell.forts:
            dist = Location.getDistance(
                latitude,
                longitude,
                fort.latitude,
                fort.longitude
            )
            if fort.type == 1 and fort.cooldown_complete_timestamp_ms<time.time():
                ordered_forts.append({'distance': dist, 'fort': fort})

    ordered_forts = sorted(ordered_forts, key=lambda k: k['distance'])
    return [instance['fort'] for instance in ordered_forts]


# Find the fort closest to user
def findClosestFort(session):
    # Find nearest fort (pokestop)
    logging.info("Finding Nearest Fort:")
    if RANDOM_ACCESS:
        return sortCloseForts(session)[np.random.randint(1,5)]
    return sortCloseForts(session)[0]



# Walk to fort and spin
def walkAndSpin(session, fort):
    # No fort, demo == over
    if fort:
        details = session.getFortDetails(fort)
        logging.info("Spinning the Fort \"%s\":" % details.name)

        # Walk over
        session.walkTo(fort.latitude, fort.longitude, step=getStep())
        # Give it a spin
        fortResponse = session.getFortSearch(fort)
        logging.info(fortResponse)


# Walk and spin everywhere
def walkAndSpinMany(session, forts):
    for fort in forts:
        walkAndSpin(session, fort)


# A very brute force approach to evolving
def evolveAllPokemon(session):
    inventory = session.checkInventory()
    for pokemon in inventory.party:
        logging.info(session.evolvePokemon(pokemon))
        time.sleep(1)


# You probably don't want to run this
def releaseAllPokemon(session):
    inventory = session.checkInventory()
    for pokemon in inventory.party:
        session.releasePokemon(pokemon)
        time.sleep(1)


# Just incase you didn't want any revives
def tossRevives(session):
    bag = session.checkInventory().bag
    return session.recycleItem(items.REVIVE, bag[items.REVIVE])


# Set an egg to an incubator
def setEgg(session):
    inventory = session.checkInventory()

    # If no eggs, nothing we can do
    if len(inventory.eggs) == 0:
        return None

    egg = inventory.eggs[0]
    incubator = inventory.incubators[0]
    return session.setEgg(incubator, egg)

def evolvePokemon(session):
    party = session.checkInventory().party
    # You may edit this list
    evolables = [pokedex.PIDGEY, pokedex.RATTATA, pokedex.ZUBAT, 
                 pokedex.CATERPIE, pokedex.WEEDLE, 
                 pokedex.DODUO]
    
    for evolve in evolables:
        pokemons = [pokemon for pokemon in party if evolve == pokemon.pokemon_id]
        candies_current = session.checkInventory().candies[evolve]
        candies_needed = pokedex.evolves[evolve]
        
        i = 0
        while i != len(pokemons) and candies_needed < candies_current:
            pokemon = pokemons[i]
            logging.info("Evolving %s" % pokedex[pokemon.pokemon_id])
            logging.info(session.evolvePokemon(pokemon))
            time.sleep(1)
            session.releasePokemon(pokemon)
            time.sleep(1)
            candies_current -= candies_needed
            i +=1
    
def releasePokemon(session, threasholdCP=500):
    party = session.checkInventory().party
    
    for pokemon in party:
        # If low cp, throw away
        if pokemon.cp < threasholdCP:
            # Get rid of low CP, low evolve value
            logging.info("Releasing %s" % pokedex[pokemon.pokemon_id])
            session.releasePokemon(pokemon)
            
# Understand this function before you run it.
# Otherwise you may flush pokemon you wanted.
def cleanPokemon(session):
    logging.info("Cleaning out Pokemon...")
    evolvePokemon(session)
    releasePokemon(session, threasholdCP=600)

def cleanInventory(session):
    logging.info("Cleaning out Inventory...")
    bag = session.checkInventory().bag

    # Clear out all of a crtain type
    tossable = [items.POTION, items.SUPER_POTION, items.REVIVE]
    for toss in tossable:
        if toss in bag and bag[toss]:
            session.recycleItem(toss, bag[toss])

    # Limit a certain type
    limited = {
        items.POKE_BALL: 50,
        items.GREAT_BALL: 100,
        items.ULTRA_BALL: 150,
        items.RAZZ_BERRY: 25
    }
    for limit in limited:
        if limit in bag and bag[limit] > limited[limit]:
            session.recycleItem(limit, bag[limit] - limited[limit])

def getStep(p=1):
    return STEP * np.random.uniform(0.5,1.0) * p

# Basic bot
def simpleBot(session):
    # Trying not to flood the servers
    cooldown = 1

    # Run the bot
    while True:
        forts = sortCloseForts(session)
        cleanPokemon(session, thresholdCP=300)
        cleanInventory(session)
        try:
            for fort in forts:
                pokemon = findBestPokemon(session)
                walkAndCatch(session, pokemon)
                walkAndSpin(session, fort)
                cooldown = 1
                time.sleep(1)

        # Catch problems and reauthenticate
        except GeneralPogoException as e:
            logging.critical('GeneralPogoException raised: %s', e)
            session = poko_session.reauthenticate(session)
            time.sleep(cooldown)
            cooldown *= 2

        except Exception as e:
            logging.critical('Exception raised: %s', e)
            session = poko_session.reauthenticate(session)
            time.sleep(cooldown)
            cooldown *= 2


# Entry point
# Start off authentication and demo
if __name__ == '__main__':
    setupLogger()
    logging.debug('Logger set up')

    print 'Read in args'
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--auth", help="Auth Service", required=True)
    parser.add_argument("-u", "--username", help="Username", required=True)
    parser.add_argument("-p", "--password", help="Password", required=True)
    parser.add_argument("-l", "--location", help="Location")
    parser.add_argument("-g", "--geo_key", help="GEO API Secret")
    args = parser.parse_args()
    
    print 'Check service'
    if args.auth not in ['ptc', 'google']:
        logging.error('Invalid auth service {}'.format(args.auth))
        sys.exit(-1)

    print 'Create PokoAuthObject'
    poko_session = PokeAuthSession(
        args.username,
        args.password,
        args.auth,
        geo_key=args.geo_key
    )

    print 'Authenticate with a given location'
    # Location is not inherent in authentication
    # But is important to session
    if MODENO == 3:
        args.location = "35.64387036252, 139.6820211410"
    elif MODENO == 4:
        args.location = "35.6717352739260, 139.764568805694"
    elif args.location == None:
        args.location = "35.6717352739260, 139.764568805694"
    
    #session start
    session = poko_session.authenticate(args.location)
    session_start_time = time.time()

    # Time to show off what we can do
    if session:

        # General
        getProfile(session)
        time.sleep(2)
        getInventory(session)
        time.sleep(2)
        cleanInventory(session)
        time.sleep(2)
        setEgg(session)

        for i in range(ROUND):
            print '-='*40
            print 'ROUND:',i+1,'(/',ROUND,')'
            print 'MODE:',MODE
            print 'session time:',round((time.time()-session_start_time)/60,3),'min'
            print 'elapsed time:',round((time.time()-start_time)/60,3),'min'
            print '-='*40
            
            # Reset location related
            if IS_RESET_LOCATION and i>0 and i%RESET_LOCATION_ROUND==0:
                print 'RESET LOCATION:',args.location
                lat, lon = map(float,args.location.split(','))
                session.walkTo(lat, lon, step=getStep(0.7))
            
            try:
                # Pokemon related
                if not POKESTOP_MARATHON:
                    cleanPokemon(session) # BE SURE TO COMFIRM IF IT'S OK TO RUN THIS!
                    pokemon = findBestPokemon(session, pids)
                    time.sleep(2)
                    walkAndCatch(session, pokemon)
        
                # Pokestop related
                fort = findClosestFort(session)
                time.sleep(2)
                walkAndSpin(session, fort)
            
                if i%50==0:
                    cleanInventory(session)
                    setEgg(session)
                    
                # Start new session
                if round((time.time()-session_start_time)/60,3) > 15:
                    print 'Start new session...Please wait about',SLEEP,'sec'
                    SLEEP_ = SLEEP/2
                    j = 0
                    p = ProgressBar(max_value=SLEEP_)
                    while SLEEP_ > j:
                        time.sleep(2)
                        j +=1
                        p.update(j)
                    session = poko_session.authenticate(args.location)
                    session_start_time = time.time()
                    
            # Catch problems and reauthenticate
            except GeneralPogoException as e:
                logging.critical('GeneralPogoException raised: %s', e)
                session = poko_session.reauthenticate(session)
                time.sleep(COOLDOWN)
                COOLDOWN *= 2
    
            except Exception as e:
                logging.critical('Exception raised: %s', e)
                session = poko_session.reauthenticate(session)
                time.sleep(COOLDOWN)
                COOLDOWN *= 2
                
            

    else:
        logging.critical('Session not created successfully')
