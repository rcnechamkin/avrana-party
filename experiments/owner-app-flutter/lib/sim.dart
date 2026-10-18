import 'package:flutter/foundation.dart';

/// Everything in this file is synthetic. No Bluetooth, Wi-Fi, network or
/// appliance is touched: state changes are timers and switches.

enum SetupStage {
  intro,
  bluetoothOff,
  permissionDenied,
  scanning,
  found,
  nothingFound,
  confirmCode,
  pairing,
  pairFailed,
  wifi,
  done,
}

/// Which failure the simulated pairing flow should run into.
enum SetupScenario { works, bluetoothOff, permissionDenied, nothingFound, pairFails }

const setupScenarioNames = {
  SetupScenario.works: 'Pairing works',
  SetupScenario.bluetoothOff: 'Bluetooth is off',
  SetupScenario.permissionDenied: 'Bluetooth permission denied',
  SetupScenario.nothingFound: 'No box found nearby',
  SetupScenario.pairFails: 'Pairing fails',
};

class FoundBox {
  const FoundBox(this.name, this.signal);
  final String name;
  final String signal;
}

const foundBoxes = [
  FoundBox('Avrana Party 7F3A', 'Strong signal'),
  FoundBox('Avrana Party C21D', 'Weak signal'),
];

enum GameState { installed, updateAvailable, updateFailed, notInstalled }

class Game {
  Game(this.id, this.name, this.category, this.players, this.version,
      this.sizeMb, this.state,
      {this.newVersion, this.summary = ''});
  final String id;
  final String name;
  final String category;
  final String players;
  final String version;
  final int sizeMb;
  GameState state;
  final String? newVersion;
  final String summary;
}

class Person {
  Person(this.name, this.status, {this.host = false});
  final String name;
  String status; // Playing, Watching, Away
  bool host;
}

class Sim extends ChangeNotifier {
  /// Simulated waits. Tests set this to zero.
  Duration wait = const Duration(milliseconds: 1400);

  // ---- setup -------------------------------------------------------------
  SetupScenario scenario = SetupScenario.works;
  SetupStage stage = SetupStage.intro;
  FoundBox? box;
  String? homeWifi;
  bool paired = false;

  void setScenario(SetupScenario value) {
    scenario = value;
    stage = SetupStage.intro;
    box = null;
    notifyListeners();
  }

  Future<void> scan() async {
    if (scenario == SetupScenario.bluetoothOff) return _go(SetupStage.bluetoothOff);
    if (scenario == SetupScenario.permissionDenied) {
      return _go(SetupStage.permissionDenied);
    }
    _go(SetupStage.scanning);
    await Future<void>.delayed(wait);
    _go(scenario == SetupScenario.nothingFound
        ? SetupStage.nothingFound
        : SetupStage.found);
  }

  void choose(FoundBox value) {
    box = value;
    _go(SetupStage.confirmCode);
  }

  Future<void> confirmCode() async {
    _go(SetupStage.pairing);
    await Future<void>.delayed(wait);
    if (scenario == SetupScenario.pairFails) return _go(SetupStage.pairFailed);
    paired = true;
    _go(SetupStage.wifi);
  }

  void chooseWifi(String? name) {
    homeWifi = name;
    _go(SetupStage.done);
  }

  void restartSetup() {
    box = null;
    _go(SetupStage.intro);
  }

  void _go(SetupStage value) {
    stage = value;
    notifyListeners();
  }

  // ---- dashboard ---------------------------------------------------------
  bool reachable = true;
  bool busy = false;
  String boxName = 'Living room box';
  String software = '1.4.2';
  String? softwareNext = '1.4.3';
  int certificateDays = 23;

  void setReachable(bool value) {
    reachable = value;
    notifyListeners();
  }

  Future<void> retry() async {
    busy = true;
    notifyListeners();
    await Future<void>.delayed(wait);
    busy = false;
    notifyListeners();
  }

  Future<void> installUpdate() async {
    busy = true;
    notifyListeners();
    await Future<void>.delayed(wait);
    software = softwareNext ?? software;
    softwareNext = null;
    busy = false;
    notifyListeners();
  }

  void renewCertificate() {
    certificateDays = 90;
    notifyListeners();
  }

  // ---- library -----------------------------------------------------------
  final games = <Game>[
    Game('bluff', 'BLUFF', 'Cards', '2 to 6', '2.3.0', 18, GameState.installed,
        summary: 'Claim a role, call a bluff, keep your coins.'),
    Game('expo', 'EXPO', 'Cards', '2 to 5', '0.9.1', 31,
        GameState.updateAvailable,
        newVersion: '0.9.2',
        summary: 'A cooperative trick-taking expedition.'),
    Game('checkers', 'Checkers', 'Board', '2', '1.0.4', 6, GameState.installed,
        summary: 'The classic, one board between two phones.'),
    Game('hello-party', 'Hello Party', 'Party', '1 to 8', '0.3.0', 2,
        GameState.updateFailed,
        newVersion: '0.3.1',
        summary: 'The reference game that ships with the Game SDK.'),
    Game('orbit-riot', 'Orbit Riot', 'Party', '2 to 8', '1.2.0', 44,
        GameState.notInstalled,
        summary: 'Slingshot around a shared planet. Last ship flying wins.'),
    Game('wordclash', 'Wordclash', 'Party', '2 to 8', '1.1.0', 12,
        GameState.notInstalled,
        summary: 'Race to build words from a shared rack.'),
  ];

  Future<void> updateGame(Game game) async {
    busy = true;
    notifyListeners();
    await Future<void>.delayed(wait);
    busy = false;
    if (game.id != 'hello-party') game.state = GameState.installed;
    notifyListeners();
  }

  void installGame(Game game) {
    game.state = GameState.installed;
    notifyListeners();
  }

  void removeGame(Game game) {
    game.state = GameState.notInstalled;
    notifyListeners();
  }

  // ---- party -------------------------------------------------------------
  bool partyActive = true;
  bool gameRunning = true;
  bool locked = false;
  final people = <Person>[
    Person('Ada', 'Playing', host: true),
    Person('Bao', 'Playing'),
    Person('Chidi', 'Watching'),
    Person('Dana', 'Away'),
  ];

  void setPartyActive(bool value) {
    partyActive = value;
    notifyListeners();
  }

  void endGame() {
    gameRunning = false;
    notifyListeners();
  }

  void setLocked(bool value) {
    locked = value;
    notifyListeners();
  }

  void passHosting(Person to) {
    for (final person in people) {
      person.host = identical(person, to);
    }
    notifyListeners();
  }

  void remove(Person person) {
    people.remove(person);
    notifyListeners();
  }
}
