import 'package:avrana_owner_prototype/main.dart';
import 'package:avrana_owner_prototype/sim.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Sim quickSim() => Sim()..wait = Duration.zero;

Future<Sim> pump(WidgetTester tester, {Size size = const Size(390, 844)}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final sim = quickSim();
  await tester.pumpWidget(OwnerPrototypeApp(sim: sim));
  return sim;
}

Future<void> open(WidgetTester tester, String place) async {
  await tester.tap(find.descendant(
      of: find.byType(NavigationBar), matching: find.text(place)));
  await tester.pumpAndSettle();
}

Future<void> expectAccessible(WidgetTester tester) async {
  final handle = tester.ensureSemantics();
  await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
  await expectLater(tester, meetsGuideline(iOSTapTargetGuideline));
  await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
  await expectLater(tester, meetsGuideline(textContrastGuideline));
  handle.dispose();
}

void main() {
  testWidgets('all four screens are reachable from the navigation bar',
      (tester) async {
    await pump(tester);
    expect(find.text('Set up your Avrana Party box'), findsOneWidget);
    await open(tester, 'Dashboard');
    expect(find.text('Living room box'), findsOneWidget);
    await open(tester, 'Library');
    expect(find.text('BLUFF'), findsOneWidget);
    await open(tester, 'Party');
    expect(find.text('Playing BLUFF'), findsOneWidget);
  });

  testWidgets('every screen says it is a prototype and marks what is simulated',
      (tester) async {
    await pump(tester);
    for (final place in ['Setup', 'Dashboard', 'Library', 'Party']) {
      await open(tester, place);
      expect(find.text('Prototype. Synthetic data, no real box.'),
          findsOneWidget);
      expect(find.text('Simulated'), findsWidgets, reason: place);
    }
  });

  testWidgets('setup pairs a box and ends on the dashboard', (tester) async {
    await pump(tester);
    await tester.tap(find.text('Find my box'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Avrana Party 7F3A'));
    await tester.pumpAndSettle();
    expect(find.text('418 207'), findsOneWidget);
    await tester.tap(find.text('They match'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Skip for now'));
    await tester.pumpAndSettle();
    expect(find.text('Your box is ready'), findsOneWidget);
    await tester.tap(find.text('Open the dashboard'));
    await tester.pumpAndSettle();
    expect(find.text('Living room box'), findsOneWidget);
  });

  testWidgets('setup shows each failure in words with a way forward',
      (tester) async {
    final sim = await pump(tester);
    const expected = {
      SetupScenario.bluetoothOff: 'Bluetooth is off',
      SetupScenario.permissionDenied: 'Avrana can’t use Bluetooth yet',
      SetupScenario.nothingFound: 'No box found nearby',
    };
    for (final entry in expected.entries) {
      sim.setScenario(entry.key);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Find my box'));
      await tester.pumpAndSettle();
      expect(find.text(entry.value), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
    }
    sim.setScenario(SetupScenario.pairFails);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Find my box'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Avrana Party 7F3A'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('They match'));
    await tester.pumpAndSettle();
    expect(find.text('Pairing didn’t finish'), findsOneWidget);
    expect(find.text('Start again'), findsOneWidget);
  });

  testWidgets('an unreachable box keeps the last data and disables controls',
      (tester) async {
    final sim = await pump(tester);
    await open(tester, 'Dashboard');
    sim.setReachable(false);
    await tester.pumpAndSettle();
    expect(find.text('This phone lost the box'), findsOneWidget);
    expect(find.text('Not reachable'), findsOneWidget);
    expect(find.text('41 of 119 GB used'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Restart box'), 200);
    final restart = tester.widget<OutlinedButton>(
        find.ancestor(of: find.text('Restart box'), matching: find.bySubtype<OutlinedButton>()));
    expect(restart.onPressed, isNull);
  });

  testWidgets('the library filters, shows an empty state and a failed update',
      (tester) async {
    await pump(tester);
    await open(tester, 'Library');
    await tester.tap(find.text('Arcade'));
    await tester.pumpAndSettle();
    expect(find.text('No Arcade games yet.'), findsOneWidget);
    await tester.tap(find.text('Show all games'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Hello Party'));
    await tester.pumpAndSettle();
    expect(find.text('The update didn’t install'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });

  testWidgets('ending the game asks first; an empty party says why',
      (tester) async {
    final sim = await pump(tester);
    await open(tester, 'Party');
    await tester.tap(find.text('End game for everyone'));
    await tester.pumpAndSettle();
    expect(find.text('End the game for everyone?'), findsOneWidget);
    await tester.tap(find.text('End game'));
    await tester.pumpAndSettle();
    expect(find.text('Between games'), findsOneWidget);
    sim.setPartyActive(false);
    await tester.pumpAndSettle();
    expect(find.text('Nobody is at the party'), findsOneWidget);
  });

  testWidgets('a wide window uses a navigation rail', (tester) async {
    await pump(tester, size: const Size(900, 700));
    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
  });

  testWidgets('targets, labels and contrast meet the guidelines on each screen',
      (tester) async {
    await pump(tester);
    for (final place in ['Setup', 'Dashboard', 'Library', 'Party']) {
      await open(tester, place);
      await expectAccessible(tester);
    }
  });

  testWidgets('nothing overflows at 200% text on a small phone',
      (tester) async {
    await pump(tester, size: const Size(360, 640));
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pumpAndSettle();
    final title = tester.getSize(find.text('Set up your Avrana Party box'));
    expect(title.height, greaterThan(60), reason: 'text really is enlarged');
    for (final place in ['Setup', 'Dashboard', 'Library', 'Party']) {
      await open(tester, place);
      expect(tester.takeException(), isNull, reason: place);
    }
  });
}
