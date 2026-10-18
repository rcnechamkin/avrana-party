import 'package:flutter/material.dart';

import 'sim.dart';
import 'theme.dart';
import 'widgets.dart';

// ---------------------------------------------------------------------------
// 1. Device setup: find a box, pair with it, choose Wi-Fi. All simulated.
// ---------------------------------------------------------------------------

class SetupScreen extends StatelessWidget {
  const SetupScreen({super.key, required this.sim, required this.onDone});
  final Sim sim;
  final VoidCallback onDone;

  static const _steps = ['Find', 'Pair', 'Wi-Fi', 'Ready'];

  int get _step => switch (sim.stage) {
        SetupStage.confirmCode ||
        SetupStage.pairing ||
        SetupStage.pairFailed =>
          1,
        SetupStage.wifi => 2,
        SetupStage.done => 3,
        _ => 0,
      };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return PageBody(children: [
      Semantics(
        label: 'Step ${_step + 1} of ${_steps.length}: ${_steps[_step]}',
        child: ExcludeSemantics(
          child: Row(children: [
            for (var i = 0; i < _steps.length; i++)
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        height: 3,
                        color: i <= _step
                            ? AvranaColors.accent
                            : AvranaColors.outlineControl,
                      ),
                      const SizedBox(height: 6),
                      Text(_steps[i],
                          style: theme.textTheme.labelMedium?.copyWith(
                              fontWeight: i == _step
                                  ? FontWeight.w700
                                  : FontWeight.w400,
                              color: i == _step
                                  ? theme.colorScheme.onSurface
                                  : theme.colorScheme.onSurfaceVariant)),
                    ],
                  ),
                ),
              ),
          ]),
        ),
      ),
      const SizedBox(height: 24),
      ..._body(context),
    ]);
  }

  List<Widget> _body(BuildContext context) {
    final theme = Theme.of(context);
    Widget headline(String text) => Semantics(
          header: true,
          child: Text(text,
              style: theme.textTheme.headlineSmall
                  ?.copyWith(fontWeight: FontWeight.w600)),
        );
    Widget lead(String text) => Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 20),
          child: Text(text,
              style: theme.textTheme.bodyLarge
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
        );
    Widget primary(String text, VoidCallback onPressed) => SizedBox(
          width: double.infinity,
          child: FilledButton(onPressed: onPressed, child: Text(text)),
        );

    switch (sim.stage) {
      case SetupStage.intro:
        return [
          headline('Set up your Avrana Party box'),
          lead('Plug the box in and stand near it. '
              'This phone finds it over Bluetooth.'),
          const Align(
              alignment: Alignment.centerLeft, child: SimulatedTag()),
          const SizedBox(height: 16),
          primary('Find my box', sim.scan),
        ];
      case SetupStage.bluetoothOff:
        return [
          headline('Bluetooth is off'),
          const SizedBox(height: 16),
          Notice(
            kind: NoticeKind.warn,
            title: 'Turn Bluetooth on to find the box',
            text: 'Open this phone’s settings, turn Bluetooth on, '
                'then try again.',
            action: 'Try again',
            onAction: sim.scan,
          ),
        ];
      case SetupStage.permissionDenied:
        return [
          headline('Avrana can’t use Bluetooth yet'),
          const SizedBox(height: 16),
          Notice(
            kind: NoticeKind.error,
            title: 'Bluetooth permission is off for this app',
            text: 'Allow Nearby devices for Avrana in this phone’s '
                'settings. It is only used to find and set up your box.',
            action: 'Try again',
            onAction: sim.scan,
          ),
        ];
      case SetupStage.scanning:
        return [
          headline('Looking for your box'),
          lead('This takes a few seconds.'),
          Semantics(
            label: 'Searching',
            child: const LinearProgressIndicator(),
          ),
        ];
      case SetupStage.nothingFound:
        return [
          headline('No box found nearby'),
          const SizedBox(height: 16),
          Notice(
            kind: NoticeKind.warn,
            title: 'Check the box is on',
            text: 'Its light should be steady. Move closer, '
                'then try again.',
            action: 'Try again',
            onAction: sim.scan,
          ),
        ];
      case SetupStage.found:
        return [
          headline('Choose your box'),
          lead('The name is printed under the box.'),
          Card(
            clipBehavior: Clip.antiAlias,
            child: Column(children: [
              for (final box in foundBoxes)
                ListTile(
                  leading: const Icon(Icons.bluetooth),
                  title: Text(box.name),
                  subtitle: Text(box.signal),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => sim.choose(box),
                ),
            ]),
          ),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: sim.scan, child: const Text('Look again')),
        ];
      case SetupStage.confirmCode:
        return [
          headline('Do the codes match?'),
          lead('${sim.box?.name} is showing a code. '
              'Continue only if it is the same as this one.'),
          Center(
            child: Semantics(
              label: 'Code 4 1 8, 2 0 7',
              child: ExcludeSemantics(
                child: Text('418 207',
                    style: theme.textTheme.displaySmall?.copyWith(
                        letterSpacing: 4, fontWeight: FontWeight.w600)),
              ),
            ),
          ),
          const SizedBox(height: 24),
          primary('They match', sim.confirmCode),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
                onPressed: sim.restartSetup,
                child: const Text('They don’t match')),
          ),
        ];
      case SetupStage.pairing:
        return [
          headline('Pairing'),
          lead('Keep this phone near the box.'),
          Semantics(
              label: 'Pairing', child: const LinearProgressIndicator()),
        ];
      case SetupStage.pairFailed:
        return [
          headline('Pairing didn’t finish'),
          const SizedBox(height: 16),
          Notice(
            kind: NoticeKind.error,
            title: 'The box stopped answering',
            text: 'Nothing was changed on the box. '
                'Stay close to it and start again.',
            action: 'Start again',
            onAction: sim.restartSetup,
          ),
        ];
      case SetupStage.wifi:
        return [
          headline('Wi-Fi for updates'),
          lead('Guests always join the box’s own network. '
              'A home network is only for updates and is optional.'),
          const Align(
              alignment: Alignment.centerLeft, child: SimulatedTag()),
          const SizedBox(height: 12),
          Card(
            clipBehavior: Clip.antiAlias,
            child: Column(children: [
              for (final name in const ['Maple House', 'Maple House 5G'])
                ListTile(
                  leading: const Icon(Icons.wifi),
                  title: Text(name),
                  trailing: const Icon(Icons.lock_outline),
                  onTap: () => sim.chooseWifi(name),
                ),
            ]),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
                onPressed: () => sim.chooseWifi(null),
                child: const Text('Skip for now')),
          ),
        ];
      case SetupStage.done:
        return [
          headline('Your box is ready'),
          lead(sim.homeWifi == null
              ? 'It works with no internet. '
                  'You can add Wi-Fi for updates later.'
              : 'It will check for updates over ${sim.homeWifi}.'),
          primary('Open the dashboard', onDone),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
                onPressed: sim.restartSetup,
                child: const Text('Set up another box')),
          ),
        ];
    }
  }
}

// ---------------------------------------------------------------------------
// 2. Device dashboard: connection, health, Wi-Fi, owner controls.
// ---------------------------------------------------------------------------

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key, required this.sim});
  final Sim sim;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final stale = !sim.reachable;
    final certWarn = sim.certificateDays < 30;
    return PageBody(children: [
      if (stale) ...[
        Notice(
          kind: NoticeKind.warn,
          title: 'This phone lost the box',
          text: 'What you see was true 2 minutes ago. '
              'Check the box is on and this phone is nearby.',
          action: sim.busy ? 'Trying…' : 'Try again',
          onAction: sim.busy ? null : sim.retry,
        ),
        const SizedBox(height: 12),
      ],
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(sim.boxName,
                  style: theme.textTheme.titleLarge
                      ?.copyWith(fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              stale
                  ? const StatusWord('Not reachable',
                      icon: Icons.link_off, color: AvranaColors.warn)
                  : const StatusWord('Connected over Wi-Fi',
                      icon: Icons.check_circle_outline,
                      color: AvranaColors.ok),
            ],
          ),
        ),
      ),
      const SectionTitle('Health', simulated: true),
      Opacity(
        opacity: stale ? 0.6 : 1,
        child: Card(
          child: Column(children: [
            const _Fact(Icons.sd_storage_outlined, 'Storage',
                '41 of 119 GB used'),
            const Divider(),
            const _Fact(Icons.thermostat, 'Temperature', 'Normal, 52 °C'),
            const Divider(),
            const _Fact(Icons.power_outlined, 'Power', 'Supply is steady'),
            const Divider(),
            _Fact(
              Icons.verified_user_outlined,
              'Secure connection',
              'Certificate renews in ${sim.certificateDays} days',
              warn: certWarn ? 'Renew soon' : null,
            ),
            const Divider(),
            _Fact(
              Icons.system_update_alt,
              'Software',
              sim.softwareNext == null
                  ? 'Version ${sim.software}, up to date'
                  : 'Version ${sim.software}',
              warn: sim.softwareNext == null
                  ? null
                  : 'Update ${sim.softwareNext} ready',
            ),
          ]),
        ),
      ),
      const SectionTitle('Wi-Fi', simulated: true),
      Opacity(
        opacity: stale ? 0.6 : 1,
        child: Card(
          child: Column(children: [
            const _Fact(Icons.wifi_tethering, 'Party network',
                'Avrana Party, 4 phones connected'),
            const Divider(),
            _Fact(
                Icons.public_off,
                'Internet',
                sim.homeWifi == null
                    ? 'Not connected. Games work without it.'
                    : 'Through ${sim.homeWifi}'),
          ]),
        ),
      ),
      const SectionTitle('Owner controls', simulated: true),
      Wrap(spacing: 8, runSpacing: 8, children: [
        if (sim.softwareNext != null)
          FilledButton.icon(
            onPressed: stale || sim.busy
                ? null
                : () async {
                    await sim.installUpdate();
                    if (context.mounted) {
                      say(context, 'Box updated to ${sim.software}.');
                    }
                  },
            icon: const Icon(Icons.download),
            label: Text(sim.busy ? 'Updating…' : 'Install update'),
          ),
        OutlinedButton.icon(
          onPressed: stale
              ? null
              : () {
                  sim.renewCertificate();
                  say(context, 'Certificate renewed for 90 days.');
                },
          icon: const Icon(Icons.autorenew),
          label: const Text('Renew certificate'),
        ),
        OutlinedButton.icon(
          onPressed: stale
              ? null
              : () async {
                  final yes = await confirm(context,
                      title: 'Restart the box?',
                      text: 'Everyone at the party is disconnected for about '
                          'a minute. A game in progress ends.',
                      action: 'Restart');
                  if (yes && context.mounted) {
                    say(context, 'Restarting. Nothing really happened: '
                        'this is a simulation.');
                  }
                },
          icon: const Icon(Icons.restart_alt),
          label: const Text('Restart box'),
        ),
      ]),
      if (stale)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text('Controls come back when the box is reachable.',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
        ),
    ]);
  }
}

class _Fact extends StatelessWidget {
  const _Fact(this.icon, this.title, this.value, {this.warn});
  final IconData icon;
  final String title;
  final String value;
  final String? warn;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon),
      title: Text(title),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(value),
          if (warn != null)
            StatusWord(warn!,
                icon: Icons.warning_amber_rounded, color: AvranaColors.warn),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 3. Game library: installed games, updates, categories, details.
// ---------------------------------------------------------------------------

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key, required this.sim});
  final Sim sim;

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  static const _filters = ['All', 'Updates', 'Cards', 'Board', 'Party', 'Arcade'];
  String _filter = 'All';

  @override
  Widget build(BuildContext context) {
    final sim = widget.sim;
    final theme = Theme.of(context);
    final shown = sim.games.where((game) => switch (_filter) {
          'All' => true,
          'Updates' => game.state == GameState.updateAvailable ||
              game.state == GameState.updateFailed,
          _ => game.category == _filter,
        }).toList();
    final updates = sim.games
        .where((game) => game.state == GameState.updateAvailable)
        .length;
    return PageBody(children: [
      Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        Text(
            '${sim.games.where((g) => g.state != GameState.notInstalled).length} '
            'installed, $updates update${updates == 1 ? '' : 's'}',
            style: theme.textTheme.bodyMedium
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
        const SimulatedTag(),
      ]),
      const SizedBox(height: 8),
      Semantics(
        label: 'Category',
        container: true,
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          for (final name in _filters)
            ChoiceChip(
              label: Text(name),
              selected: _filter == name,
              onSelected: (_) => setState(() => _filter = name),
            ),
        ]),
      ),
      const SizedBox(height: 12),
      if (shown.isEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 32),
          child: Column(children: [
            Icon(Icons.inbox_outlined,
                size: 32, color: theme.colorScheme.onSurfaceVariant),
            const SizedBox(height: 8),
            Text(
                _filter == 'Updates'
                    ? 'Every game is up to date.'
                    : 'No $_filter games yet.',
                style: theme.textTheme.bodyLarge),
            const SizedBox(height: 8),
            OutlinedButton(
                onPressed: () => setState(() => _filter = 'All'),
                child: const Text('Show all games')),
          ]),
        )
      else
        Card(
          clipBehavior: Clip.antiAlias,
          child: Column(children: [
            for (final (index, game) in shown.indexed) ...[
              if (index > 0) const Divider(),
              ListTile(
                leading: _Cover(game),
                title: Text(game.name),
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${game.category}, ${game.players} players'),
                    _GameStatus(game),
                  ],
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                    builder: (_) => GameDetailScreen(sim: sim, game: game))),
              ),
            ],
          ]),
        ),
    ]);
  }
}

class _Cover extends StatelessWidget {
  const _Cover(this.game, {this.size = 48});
  final Game game;
  final double size;

  @override
  Widget build(BuildContext context) {
    final icon = switch (game.category) {
      'Cards' => Icons.style_outlined,
      'Board' => Icons.grid_on,
      _ => Icons.sports_esports_outlined,
    };
    return ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: AvranaColors.surfaceRaised,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AvranaColors.outlineQuiet),
        ),
        child: Icon(icon, color: AvranaColors.accent, size: size * 0.5),
      ),
    );
  }
}

class _GameStatus extends StatelessWidget {
  const _GameStatus(this.game);
  final Game game;

  @override
  Widget build(BuildContext context) {
    return switch (game.state) {
      GameState.installed => StatusWord('Installed, version ${game.version}',
          icon: Icons.check_circle_outline, color: AvranaColors.ok),
      GameState.updateAvailable => StatusWord(
          'Update ${game.newVersion} available',
          icon: Icons.arrow_circle_up,
          color: AvranaColors.info),
      GameState.updateFailed => const StatusWord('Update failed',
          icon: Icons.error_outline, color: AvranaColors.error),
      GameState.notInstalled =>
        const StatusWord('Not installed', icon: Icons.cloud_off_outlined),
    };
  }
}

class GameDetailScreen extends StatelessWidget {
  const GameDetailScreen({super.key, required this.sim, required this.game});
  final Sim sim;
  final Game game;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: sim,
      builder: (context, _) {
        final theme = Theme.of(context);
        return Scaffold(
          appBar: AppBar(title: const Text('Library')),
          body: PageBody(children: [
            Row(children: [
              _Cover(game, size: 72),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Semantics(
                      header: true,
                      child: Text(game.name,
                          style: theme.textTheme.headlineSmall
                              ?.copyWith(fontWeight: FontWeight.w600)),
                    ),
                    _GameStatus(game),
                  ],
                ),
              ),
            ]),
            const SizedBox(height: 16),
            Text(game.summary, style: theme.textTheme.bodyLarge),
            const SizedBox(height: 16),
            Card(
              child: Column(children: [
                _Fact(Icons.group_outlined, 'Players', game.players),
                const Divider(),
                _Fact(Icons.category_outlined, 'Category', game.category),
                const Divider(),
                _Fact(Icons.sd_storage_outlined, 'Size on the box',
                    '${game.sizeMb} MB'),
              ]),
            ),
            if (game.state == GameState.updateFailed) ...[
              const SizedBox(height: 16),
              Notice(
                kind: NoticeKind.error,
                title: 'The update didn’t install',
                text: 'The box kept version ${game.version}, which still '
                    'plays. The download was incomplete.',
                action: sim.busy ? 'Trying…' : 'Try again',
                onAction: sim.busy ? null : () => sim.updateGame(game),
              ),
            ],
            const SizedBox(height: 16),
            const Align(
                alignment: Alignment.centerLeft, child: SimulatedTag()),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (game.state == GameState.updateAvailable)
                FilledButton(
                  onPressed: sim.busy ? null : () => sim.updateGame(game),
                  child: Text(sim.busy
                      ? 'Updating…'
                      : 'Update to ${game.newVersion}'),
                ),
              if (game.state == GameState.notInstalled)
                FilledButton(
                  onPressed: () => sim.installGame(game),
                  child: const Text('Install on the box'),
                )
              else
                OutlinedButton(
                  onPressed: () async {
                    final yes = await confirm(context,
                        title: 'Remove ${game.name}?',
                        text: 'It is removed from the box for everyone. '
                            'You can install it again later.',
                        action: 'Remove');
                    if (yes) sim.removeGame(game);
                  },
                  style: OutlinedButton.styleFrom(
                      foregroundColor: AvranaColors.error),
                  child: const Text('Remove from the box'),
                ),
            ]),
          ]),
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// 4. Party management: who is here, what is being played, host controls.
// ---------------------------------------------------------------------------

class PartyScreen extends StatelessWidget {
  const PartyScreen({super.key, required this.sim});
  final Sim sim;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (!sim.partyActive) {
      return PageBody(children: [
        const SizedBox(height: 48),
        Icon(Icons.groups_outlined,
            size: 40, color: theme.colorScheme.onSurfaceVariant),
        const SizedBox(height: 12),
        Text('Nobody is at the party',
            textAlign: TextAlign.center, style: theme.textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(
            'Phones that join the Avrana Party Wi-Fi appear here. '
            'Guests need no app.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
      ]);
    }
    final host = sim.people.firstWhere((p) => p.host,
        orElse: () => sim.people.first);
    return PageBody(children: [
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                  spacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(sim.gameRunning ? 'Playing BLUFF' : 'Between games',
                        style: theme.textTheme.titleLarge
                            ?.copyWith(fontWeight: FontWeight.w600)),
                    const SimulatedTag(),
                  ]),
              const SizedBox(height: 4),
              Text(
                  sim.gameRunning
                      ? 'Round 3, started 12 minutes ago. '
                          '${host.name} is hosting.'
                      : '${host.name} is hosting and picks the next game.',
                  style: theme.textTheme.bodyMedium
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
              if (sim.gameRunning) ...[
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: () async {
                    final yes = await confirm(context,
                        title: 'End the game for everyone?',
                        text: 'BLUFF stops for all ${sim.people.length} '
                            'people and the party goes back to its home.',
                        action: 'End game');
                    if (yes) sim.endGame();
                  },
                  icon: const Icon(Icons.stop_circle_outlined),
                  label: const Text('End game for everyone'),
                ),
              ],
            ],
          ),
        ),
      ),
      SectionTitle('People here (${sim.people.length})'),
      Card(
        clipBehavior: Clip.antiAlias,
        child: Column(children: [
          for (final (index, person) in sim.people.indexed) ...[
            if (index > 0) const Divider(),
            ListTile(
              leading: CircleAvatar(
                backgroundColor: AvranaColors.surfaceRaised,
                foregroundColor: theme.colorScheme.onSurface,
                child: Text(person.name.substring(0, 1)),
              ),
              title: Wrap(
                  spacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(person.name),
                    if (person.host)
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6),
                        decoration: BoxDecoration(
                          border: Border.all(
                              color: AvranaColors.outlineControl),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child:
                            Text('Host', style: theme.textTheme.labelSmall),
                      ),
                  ]),
              subtitle: StatusWord(person.status,
                  icon: switch (person.status) {
                    'Playing' => Icons.sports_esports_outlined,
                    'Watching' => Icons.visibility_outlined,
                    _ => Icons.bedtime_outlined,
                  }),
              trailing: PopupMenuButton<String>(
                tooltip: 'Options for ${person.name}',
                onSelected: (choice) async {
                  if (choice == 'host') {
                    sim.passHosting(person);
                    say(context, '${person.name} is hosting now.');
                  } else {
                    final yes = await confirm(context,
                        title: 'Remove ${person.name}?',
                        text: 'Their phone leaves the party. '
                            'They can join again.',
                        action: 'Remove');
                    if (yes) sim.remove(person);
                  }
                },
                itemBuilder: (_) => [
                  if (!person.host)
                    const PopupMenuItem(
                        value: 'host', child: Text('Pass hosting')),
                  const PopupMenuItem(
                      value: 'remove', child: Text('Remove from party')),
                ],
              ),
            ),
          ],
        ]),
      ),
      const SectionTitle('Session', simulated: true),
      Card(
        child: SwitchListTile(
          value: sim.locked,
          onChanged: sim.setLocked,
          title: const Text('Hold new arrivals'),
          subtitle: Text(sim.locked
              ? 'New phones wait until you let them in.'
              : 'Anyone on the Avrana Party Wi-Fi can join.'),
        ),
      ),
    ]);
  }
}
