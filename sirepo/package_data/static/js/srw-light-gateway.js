'use strict';

var SRW_EXAMPLES;

SIREPO.srlog = console.log.bind(console);
SIREPO.srdbg = console.log.bind(console);

var srlog = SIREPO.srlog;
var srdbg = SIREPO.srdbg;


SIREPO.app.controller('SRWLightController', function (requestSender, $http, $location) {
    var self = this;
    self.location = $location;

    requestSender.sendRequest('/static/json/srw-examples.json' + SIREPO.SOURCE_CACHE_KEY,
    function (data, respStatus) {
        srdbg('got examples', data);
        SRW_EXAMPLES = data;
    }, {});

    function pageCategory() {
        return $location.path().substring(1);
    }


    self.itemsForCategory = function() {
        for (var i = 0; i < self.srwExamples.length; i++) {
            if (self.srwExamples[i].category == pageCategory()) {
                return self.srwExamples[i].examples;
            }
        }
    };

    self.itemUrl = function(item) {
        if (item.category) {
            return '#/' + item.category;
        }
        return '/find-by-name/srw/' + pageCategory() + '/' + encodeURIComponent(item.simulationName || item.name);
    };

    self.pageName = function() {
        return SIREPO.APP_SCHEMA.localRoutes[pageCategory()];
    };

    self.pageTitle = function() {
        if (SIREPO.IS_SRW_LANDING_PAGE) {
            var name = self.pageName();
            return (name ? (name + ' - ') : '') + 'Synchrotron Radiation Workshop - Radiasoft';
        }
        return 'Sirepo - Radiasoft';
    };

    self.onMainLandingPage = function () {
        return $location.path() === '/about';
    };

    self.getModeMap = function(route) {
        return SIREPO.APP_SCHEMA.appRoutes[route].modeMap;
    };

});

SIREPO.app.directive('srwLightGateway', function(appState, requestSender, $location) {

    return {
        restrict: 'A',
        scope: {
            route: '=',
        },
        controller: function($scope) {
            var self = this;

            this.template = [
                            '<div data-page-heading="" data-page-name="', self.pageName(), '"></div>',
                            '<div class="container">',
                                '<div class="row visible-xs">',
                                    '<div class="lead text-center" data-ng-bind="', self.pageName(), '"></div>',
                                '</div>',
                                '<div data-ng-repeat="item in landingPage.itemsForCategory()" data-',
                                ($scope.route == 'light-sources' ? 'button-list' : 'big-button'),
                                '="item"></div>',
                            '</div>',
            ].join('');

            self.srwExamples = SRW_EXAMPLES;
            self.location = $location;

            function pageCategory() {
                return $location.path().substring(1);
            }

            self.itemsForCategory = function() {
                for (var i = 0; i < self.srwExamples.length; i++) {
                    if (self.srwExamples[i].category == pageCategory()) {
                        return self.srwExamples[i].examples;
                    }
                }
            };

            self.itemUrl = function(item) {
                if (item.category) {
                    return '#/' + item.category;
                }
                return '/find-by-name/srw/' + pageCategory() + '/' + encodeURIComponent(item.simulationName || item.name);
            };

            self.pageName = function() {
                return SIREPO.APP_SCHEMA.localRoutes[pageCategory()];
            };

            self.pageTitle = function() {
                var name = self.pageName();
                return (name ? (name + ' - ') : '') + 'Synchrotron Radiation Workshop - Radiasoft';
            };

            self.onMainLandingPage = function () {
                return $location.path() === '/about';
            };

            self.getModeMap = function(route) {
                return SIREPO.APP_SCHEMA.appRoutes[route].modeMap;
            };
        },
    };
});

SIREPO.app.directive('pageHeading', function() {
    return {
        restrict: 'A',
        scope: {
            pageName: '=',
        },
        template: [
                '<div class="lp-main-header-content">',
                    '<a href="/#about">',
                        '<img class="lp-header-sr-logo" src="/static/img/SirepoLogo.png',SIREPO.SOURCE_CACHE_KEY,'">',
                    '</a>',
                    '<div class="lp-srw-sub-header-text">',
                        '<a href="/#/srw">Synchrotron Radiation Workshop</a>',
                        ' <span class="hidden-xs" data-ng-if="pageName">-</span> ',
                        '<span class="hidden-xs" data-ng-if="pageName" data-ng-bind="pageName"></span>',
                    '</div>',
                    '<div class="pull-right">',
                        '<a href="http://radiasoft.net">',
                            '<img class="lp-header-rs-logo" src="/static/img/RSLogo.png',SIREPO.SOURCE_CACHE_KEY,'" alt="Radiasoft" />',
                        '</a>',
                    '</div>',
                '</div>',
        ].join(''),
        controller: function() {
        },
    };
});


SIREPO.app.directive('bigButton', function() {
    return {
        restrict: 'A',
        scope: {
            item: '=bigButton',
            wideCol: '@',
        },
        template: [
            '<div class="row">',
              '<div data-ng-class="item.class">',
                '<a data-ng-href="{{ item.url }}" class="btn btn-default thumbnail lp-big-button"><h3 data-ng-if="item.name">{{ item.name }}</h3><img data-ng-if="item.image" data-ng-src="/static/img/{{ item.image }}" alt="{{ item.name }}" /><span class="lead text-primary" style="white-space: pre" data-ng-if="item.buttonText">{{ item.buttonText }}</span></a>',
              '</div>',
            '</div>',
        ].join(''),
        controller: function($scope) {
            var current = $scope;
            var controller;
            while (current) {
                controller = current.landingPage;
                if (controller) {
                    break;
                }
                current = current.$parent;
            }
            $scope.item.class = $scope.wideCol
                ? 'col-md-8 col-md-offset-2'
                : 'col-md-6 col-md-offset-3';
            $scope.item.url = controller.itemUrl($scope.item);
        },
    };
});

SIREPO.app.directive('buttonList', function() {
    return {
        restrict: 'A',
        scope: {
            item: '=buttonList',
        },
        template: [
            '<div class="row">',
              '<div class="col-md-8 col-md-offset-2">',
                '<div class="well">',
                  '<h3>{{ item.name }}</h3>',
                  '<div data-ng-repeat="item in item.simulations" data-big-button="item" data-wide-col="1"></div>',
                '</div>',
              '</div>',
            '</div>',
        ].join(''),
    };
});
