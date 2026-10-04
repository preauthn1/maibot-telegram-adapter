"""校验 JUnit 声明计数与实际条目，拒绝空报告和不一致证据。"""
import xml.etree.ElementTree as ET


def verified_counts(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == 'testsuite' else list(root.findall('testsuite'))
    if not suites:
        raise ValueError('Missing test suites')
    totals = dict.fromkeys(('tests', 'failures', 'errors', 'skipped'), 0)
    for suite in suites:
        cases = suite.findall('testcase')
        observed = {'tests': len(cases)}
        for key, tag in [('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')]:
            observed[key] = sum(case.find(tag) is not None for case in cases)
        declared = {key: int(suite.attrib[key]) for key in totals}
        if observed != declared:
            raise ValueError('JUnit counts disagree with test cases')
        for key in totals:
            totals[key] += observed[key]
    if totals['tests'] == 0:
        raise ValueError('Empty test report')
    return totals
