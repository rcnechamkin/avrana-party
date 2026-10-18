import 'package:flutter/material.dart';

import 'screens.dart';
import 'sim.dart';
import 'theme.dart';
import 'widgets.dart';

void main() => runApp(OwnerPrototypeApp(sim: Sim()));

/// A non-production prototype of the planned Avrana Party owner app.
/// Four screens on synthetic data; see README.md for what is simulated.
class OwnerPrototypeApp extends StatelessWidget {
  const OwnerPrototypeApp({super.key, required this.sim});
  final Sim sim;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Avrana Party owner prototype',
      debugShowCheckedModeBanner: false,
      theme: avranaTheme(),
      home: Shell(sim: sim),
    );
  }
}

class _Place {
  const _Place(this.label, this.icon, this.selectedIcon);
  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

const _places = [
  _Place('Setup', Icons.bluetooth_searching, Icons.bluetooth_connected),
  _Place('Dashboard', Icons.dashboard_outlined, Icons.dashboard),
  _Place('Library', Icons.grid_view_outlined, Icons.grid_view_rounded),
  _Place('Party', Icons.groups_outlined, Icons.groups),
];

class Shell extends StatefulWidget {
  const Shell({super.key, required this.sim});
  final Sim sim;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _index = 0;

  void _go(int index) => setState(() => _index = index);

  @override
  Widget build(BuildContext context) {
    final sim = widget.sim;
    return ListenableBuilder(
      listenable: sim,
      builder: (context, _) {
        final wide = MediaQuery.sizeOf(context).width >= 600;
        final body = switch (_index) {
          0 => SetupScreen(sim: sim, onDone: () => _go(1)),
          1 => DashboardScreen(sim: sim),
          2 => LibraryScreen(sim: sim),
          _ => PartyScreen(sim: sim),
        };
        return Scaffold(
          appBar: AppBar(
            title: Text(_places[_index].label),
            actions: [
              IconButton(
                tooltip: 'Prototype scenarios',
                icon: const Icon(Icons.science_outlined),
                onPressed: () => _scenarios(context),
              ),
              IconButton(
                tooltip: 'About this prototype',
                icon: const Icon(Icons.info_outline),
                onPressed: () => _about(context),
              ),
            ],
          ),
          body: SafeArea(
            child: Column(children: [
              const _PrototypeBar(),
              Expanded(
                child: wide
                    ? Row(children: [
                        NavigationRail(
                          selectedIndex: _index,
                          onDestinationSelected: _go,
                          labelType: NavigationRailLabelType.all,
                          destinations: [
                            for (final place in _places)
                              NavigationRailDestination(
                                icon: Icon(place.icon),
                                selectedIcon: Icon(place.selectedIcon),
                                label: Text(place.label),
                              ),
                          ],
                        ),
                        const VerticalDivider(width: 1),
                        Expanded(child: body),
                      ])
                    : body,
              ),
            ]),
          ),
          bottomNavigationBar: wide
              ? null
              : NavigationBar(
                  selectedIndex: _index,
                  onDestinationSelected: _go,
                  destinations: [
                    for (final place in _places)
                      NavigationDestination(
                        icon: Icon(place.icon),
                        selectedIcon: Icon(place.selectedIcon),
                        label: place.label,
                      ),
                  ],
                ),
        );
      },
    );
  }

  void _scenarios(BuildContext context) {
    final sim = widget.sim;
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => ListenableBuilder(
        listenable: sim,
        builder: (context, _) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            children: [
              Semantics(
                header: true,
                child: Text('Prototype scenarios',
                    style: Theme.of(context).textTheme.titleLarge),
              ),
              const SizedBox(height: 4),
              const Text('Switch the pretend conditions to see each state.'),
              const SectionTitle('Setup'),
              RadioGroup<SetupScenario>(
                groupValue: sim.scenario,
                onChanged: (value) => sim.setScenario(value!),
                child: Column(children: [
                  for (final entry in setupScenarioNames.entries)
                    RadioListTile<SetupScenario>(
                      value: entry.key,
                      title: Text(entry.value),
                      contentPadding: EdgeInsets.zero,
                    ),
                ]),
              ),
              const SectionTitle('Dashboard'),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Box is reachable'),
                value: sim.reachable,
                onChanged: sim.setReachable,
              ),
              const SectionTitle('Party'),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('People are at the party'),
                value: sim.partyActive,
                onChanged: sim.setPartyActive,
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _about(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          children: [
            Semantics(
              header: true,
              child: Text('About this prototype',
                  style: Theme.of(context).textTheme.titleLarge),
            ),
            const SectionTitle('Real in this build'),
            const Text('Navigation between the four screens, the layouts at '
                'phone and tablet widths, the Avrana Party theme on Material 3 '
                'widgets, and how each screen draws loading, empty, error and '
                'out-of-reach states.'),
            const SectionTitle('Simulated'),
            const Text('Bluetooth scanning and pairing, the pairing code, '
                'joining Wi-Fi, every health figure, updates, certificate '
                'renewal, restarting the box, the game list, installs and '
                'removals, the people at the party and every host control. '
                'Nothing leaves this phone and no box is contacted.'),
            const SectionTitle('Not decided here'),
            const Text('Whether Flutter is used, who may remove a guest or '
                'pass hosting, and how pairing really works. See the '
                'feasibility finding in the repository.'),
          ],
        ),
      ),
    );
  }
}

class _PrototypeBar extends StatelessWidget {
  const _PrototypeBar();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AvranaColors.surfaceLow,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Text('Prototype. Synthetic data, no real box.',
          style: Theme.of(context)
              .textTheme
              .labelMedium
              ?.copyWith(color: AvranaColors.warn)),
    );
  }
}
