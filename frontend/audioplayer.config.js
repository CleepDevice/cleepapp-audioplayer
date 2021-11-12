/**
 * Audioplayer config component
 * Handle audioplayer application configuration
 * If your application doesn't need configuration page, delete this file and its references into desc.json
 */
angular
.module('Cleep')
.directive('audioplayerConfigComponent', ['$rootScope', 'cleepService', 'toastService', 'audioplayerService', '$mdDialog',
function($rootScope, cleepService, toastService, audioplayerService, $mdDialog) {

    var audioplayerConfigController = function() {
        var self = this;
        self.audioplayerService = audioplayerService;
        self.formats = [
            { label: 'mp3', value: 'audio/mpeg' },
            { label: 'aac', value: 'audio/aac' },
            { label: 'ogg', value: 'audio/ogg' },
            { label: 'flac', value: 'audio/flac' },
        ];
        self.selectedFormat = 'audio/mpeg';
        self.url = '/root/temp/placebo.mp3';
        self.trackIndex = 0;
        self.playlist = undefined;
        self.selectedPlayerId = undefined;
        self.volume = 100;
        self.repeat = false;

        self.$onInit = function() {
            audioplayerService.refreshPlayers();
        };

        self.play = function() {
            audioplayerService.play(self.url, self.selectedFormat);
        };

        self.pause = function(playerId) {
            audioplayerService.pause(playerId);
        };

        self.stop = function(playerId) {
            audioplayerService.stop(playerId);
            self.cancelDialog();
        };

        self.next = function(playerId) {
            audioplayerService.next(playerId);
        };

        self.previous = function(playerId) {
            audioplayerService.previous(playerId);
        };

        self.setVolume = function(playerId) {
            audioplayerService.setVolume(playerId, self.volume);
        };

        self.setRepeat = function(playerId) {
            audioplayerService.setRepeat(playerId, self.repeat);
        };

        self.shufflePlaylist = function(playerId) {
            audioplayerService.shufflePlaylist(playerId)
                .then((response) => {
                    if (response.error) {
                        return;
                    }
                    self.loadPlaylist(self.selectedPlayerId);
                });
        };

        self.addTrack = function(playerId) {
            audioplayerService.addTrack(self.selectedPlayerId, self.url, self.selectedFormat, self.trackIndex)
                .then((response) => {
                    if (response.error) {
                        return;
                    }
                    self.loadPlaylist(self.selectedPlayerId);
                });
        };

        self.removeTrack = function(playerId, trackIndex) {
            audioplayerService.removeTrack(playerId, trackIndex)
                .then((response) => {
                    if (response.error) {
                        return;
                    }
                    self.loadPlaylist(self.selectedPlayerId);
                });
        };

        self.loadPlaylist = function(playerId) {
            return audioplayerService.getPlaylist(playerId)
                .then((response) => {
                    self.playlist = response.data;
                    self.selectedPlayerId = playerId;
                    self.repeat = self.playlist.repeat;
                    self.volume = self.playlist.volume;
                });
        };

        self.showPlaylist = function(playerId) {
            self.loadPlaylist(playerId).then(() => {
                self.openDialog();
            });
        };

        self.openDialog = function() {
            return $mdDialog.show({
                controller: function() { return self; },
                controllerAs: 'audioplayerCtl',
                templateUrl: 'playlist.dialog.html',
                parent: angular.element(document.body),
                clickOutsideToClose: false,
                fullscreen: true,
            });
        };

        self.cancelDialog = function() {
            $mdDialog.cancel();
        };
    };

    return {
        templateUrl: 'audioplayer.config.html',
        replace: true,
        scope: true,
        controller: audioplayerConfigController,
        controllerAs: 'audioplayerCtl',
    };
}]);
